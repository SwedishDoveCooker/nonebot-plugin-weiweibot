// Command vvbot is a QQ official group bot that serves the VV picture library.
package main

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"

	"gopkg.in/natefinch/lumberjack.v2"

	"vvbot/internal/bot"
	"vvbot/internal/lib"
	"vvbot/internal/qq"
	"vvbot/internal/sdnotify"
)

func env(key, def string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return def
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "fatal:", err)
		os.Exit(1)
	}
}

func run() error {
	appID, secret := env("QQ_APPID", ""), env("QQ_SECRET", "")
	if appID == "" || secret == "" {
		return fmt.Errorf("QQ_APPID and QQ_SECRET are required")
	}
	dataDir := env("VV_DATA_DIR", "/mnt/ssd/vvbot/data")

	var out io.Writer = os.Stderr
	if lf := env("VV_LOG_FILE", ""); lf != "" {
		if err := os.MkdirAll(filepath.Dir(lf), 0o755); err != nil {
			return err
		}
		out = io.MultiWriter(os.Stderr, &lumberjack.Logger{Filename: lf, MaxSize: 10, MaxBackups: 5, MaxAge: 30, Compress: true})
	}
	log := slog.New(slog.NewTextHandler(out, &slog.HandlerOptions{Level: slog.LevelInfo}))

	groups := map[string]bool{}
	for _, g := range strings.Split(env("VV_GROUPS", ""), ",") {
		if g = strings.TrimSpace(g); g != "" {
			groups[g] = true
		}
	}

	holder := &lib.Holder{}
	libDirs := strings.Split(env("VV_LIB_DIRS", filepath.Join(dataDir, "legacy")), ",")
	reload := func() {
		var all []lib.Entry
		for _, d := range libDirs {
			l, err := lib.LoadDir(strings.TrimSpace(d))
			if err != nil {
				log.Error("load library", "dir", d, "err", err)
				continue
			}
			all = append(all, l.Entries()...)
		}
		if len(all) == 0 && holder.Get().Len() > 0 {
			log.Error("reload produced an empty library, keeping the old one")
			return
		}
		holder.Set(lib.New(all))
		log.Info("library loaded", "entries", len(all))
	}
	reload()

	hc := &http.Client{Timeout: 30 * time.Second}
	ts := qq.NewTokenSource(appID, secret, hc)
	api := qq.NewClient(ts, hc, log)
	b := bot.New(api, holder, bot.Config{Groups: groups, UploadDir: filepath.Join(dataDir, "uploads"), EnableUpload: env("VV_ENABLE_UPLOAD", "") == "1"}, log)

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

	gw := qq.NewGateway(api, ts, qq.IntentGroupAndC2C, b.HandleEvent, func() { sdnotify.Send("READY=1") }, log)

	// Feed the systemd watchdog only while the gateway is healthy, so a wedged
	// connection ends in a restart instead of a silent bot.
	if iv := sdnotify.WatchdogInterval(); iv > 0 {
		go func() {
			t := time.NewTicker(iv)
			defer t.Stop()
			started := time.Now()
			for {
				select {
				case <-ctx.Done():
					return
				case <-t.C:
					if gw.Healthy() || time.Since(started) < 3*time.Minute {
						sdnotify.Send("WATCHDOG=1")
					}
				}
			}
		}()
	}

	// Pick up library changes (weekly index updates) without restarting.
	go func() {
		every, _ := strconv.Atoi(env("VV_RELOAD_MINUTES", "10"))
		t := time.NewTicker(time.Duration(every) * time.Minute)
		defer t.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-t.C:
				reload()
			}
		}
	}()

	log.Info("vvbot starting", "appid", appID, "data", dataDir, "groups", len(groups))
	gw.Run(ctx)
	log.Info("vvbot stopped")
	return nil
}
