// Command vvbot is a QQ official group bot that serves the VV picture library.
package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"gopkg.in/natefinch/lumberjack.v2"

	vvapi "vvbot/internal/api"
	"vvbot/internal/bot"
	"vvbot/internal/lib"
	"vvbot/internal/llm"
	"vvbot/internal/ops"
	"vvbot/internal/qq"
	"vvbot/internal/sdnotify"
	"vvbot/internal/sem"
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
	if (appID == "" || secret == "") && env("VV_MODE", "bot") != "search" {
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
	notifier := ops.NewNotifier(env("VV_NOTIFY_GROUP", ""))
	log := slog.New(ops.WrapLogHandler(slog.NewTextHandler(out, &slog.HandlerOptions{Level: slog.LevelInfo}), notifier))

	groups := map[string]bool{}
	for _, g := range strings.Split(env("VV_GROUPS", ""), ",") {
		if g = strings.TrimSpace(g); g != "" {
			groups[g] = true
		}
	}

	holder := &lib.Holder{}
	libDirs := strings.Split(env("VV_LIB_DIRS", filepath.Join(dataDir, "legacy")), ",")
	indexDir := env("VV_INDEX_DIR", filepath.Join(dataDir, "index"))
	minSim, err := strconv.ParseFloat(env("VV_MIN_SIM", "0.36"), 64)
	if err != nil {
		return fmt.Errorf("VV_MIN_SIM: %w", err)
	}
	semMin, err := strconv.ParseFloat(env("VV_SEM_MIN", "0.66"), 64)
	if err != nil {
		return fmt.Errorf("VV_SEM_MIN: %w", err)
	}
	reload := func() {
		// Index entries go first: the vector rows point into this slice.
		all, vec, skipped, err := lib.LoadIndex(indexDir)
		if err != nil {
			log.Error("load index", "dir", indexDir, "err", err)
			all, vec = nil, nil
		}
		for _, s := range skipped {
			log.Warn("index episode skipped", "why", s)
		}
		for _, d := range libDirs {
			if d = strings.TrimSpace(d); d == "" {
				continue
			}
			es, err := lib.LoadDir(d)
			if err != nil {
				log.Error("load library", "dir", d, "err", err)
				continue
			}
			all = append(all, es...)
		}
		if len(all) == 0 && holder.Get().Len() > 0 {
			log.Error("reload produced an empty library, keeping the old one")
			return
		}
		holder.Set(lib.NewWithVec(all, vec))
		log.Info("library loaded", "entries", len(all), "vectors", vec.Rows())
	}
	reload()

	hc := &http.Client{Timeout: 30 * time.Second}
	ts := qq.NewTokenSource(appID, secret, hc)
	api := qq.NewClient(ts, hc, log)
	notifier.Bind(api, log)

	store, err := ops.OpenStore(filepath.Join(dataDir, "state", "state.json"))
	if err != nil {
		return fmt.Errorf("open state: %w", err)
	}
	weekly := ops.NewWeekly(store, notifier, filepath.Join(dataDir, "secrets"), log)
	weekly.JobsDir = filepath.Join(dataDir, "jobs")

	// Groups where the bot may answer picture requests without being addressed ("*" = every group).
	proactiveGroups, proactiveAll := map[string]bool{}, false
	for _, g := range strings.Split(env("VV_PROACTIVE_GROUPS", ""), ",") {
		switch g = strings.TrimSpace(g); g {
		case "":
		case "*":
			proactiveAll = true
		default:
			proactiveGroups[g] = true
		}
	}

	owners := map[string]bool{}
	for _, o := range strings.Split(env("VV_OWNERS", ""), ",") {
		if o = strings.TrimSpace(o); o != "" {
			owners[o] = true
		}
	}
	b := bot.New(api, holder, bot.Config{
		Groups: groups, UploadDir: filepath.Join(dataDir, "uploads"),
		EnableUpload: env("VV_ENABLE_UPLOAD", "") == "1", Owners: owners, MinSim: minSim,
		SemMin: semMin, Proactive: proactiveGroups, ProactiveAll: proactiveAll,
	}, bot.Extras{
		Weekly: weekly, Notifier: notifier, Library: func() int { return holder.Get().Len() },
		Embedder: sem.New(env("VV_EMBED_URL", "http://127.0.0.1:8765")),
		LLM:      llm.New(env("VV_LLM_URL", ""), env("VV_LLM_KEY", ""), env("VV_LLM_MODEL", "default"), 20*time.Second),
	}, log)

	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()

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

	// The local HTTP interface for other programs. VV_MODE selects what runs:
	//   bot    (default) the QQ gateway plus the weekly watcher and notifications
	//   ops    everything except the QQ gateway: for when another program (AstrBot) holds the connection
	//   search only the picture API, no QQ and no state
	mode := env("VV_MODE", "bot")
	apiAddr := env("VV_API_ADDR", "")
	if (mode == "search" || mode == "ops") && apiAddr == "" {
		apiAddr = "127.0.0.1:8770"
	}
	if apiAddr != "" {
		var owner vvapi.Owner
		if mode != "search" {
			owner = ownerAPI{w: weekly, lib: func() int { return holder.Get().Len() }}
		}
		handler := vvapi.Handler(b, owner, strings.TrimSpace(env("VV_API_TOKEN", "")))
		srv := &http.Server{Addr: apiAddr, Handler: handler, ReadHeaderTimeout: 5 * time.Second}
		go func() {
			if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
				log.Error("api server", "addr", apiAddr, "err", err)
			}
		}()
		go func() {
			<-ctx.Done()
			sc, cancel := context.WithTimeout(context.Background(), 3*time.Second)
			defer cancel()
			_ = srv.Shutdown(sc)
		}()
		log.Info("api listening", "addr", apiAddr)
	}
	if mode == "search" || mode == "ops" {
		if mode == "ops" {
			go weekly.Start(ctx)
			go weekly.Run(ctx)
			go notifier.WatchDropbox(ctx, filepath.Join(dataDir, "notify"), log)
		}
		sdnotify.Send("READY=1")
		<-ctx.Done()
		if mode == "ops" {
			weekly.MarkClean()
		}
		return nil
	}

	var once sync.Once
	gw := qq.NewGateway(api, ts, qq.IntentGroupAndC2C, b.HandleEvent, func() {
		sdnotify.Send("READY=1")
		once.Do(func() { go weekly.Start(ctx) })
	}, log)
	go weekly.Run(ctx)
	go notifier.WatchDropbox(ctx, filepath.Join(dataDir, "notify"), log)

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

	log.Info("vvbot starting", "appid", appID, "data", dataDir, "groups", len(groups))
	gw.Run(ctx)
	weekly.MarkClean()
	log.Info("vvbot stopped")
	return nil
}
