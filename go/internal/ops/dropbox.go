package ops

import (
	"context"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

const (
	dropboxEvery   = 20 * time.Second
	dropboxMaxBody = 4000
)

// drainDir hands the text of every *.txt file in dir to send and then removes the file.
// Files that are still being written use another extension (*.tmp) and are left alone.
func drainDir(dir string, send func(string)) int {
	names, err := filepath.Glob(filepath.Join(dir, "*.txt"))
	if err != nil {
		return 0
	}
	sort.Strings(names)
	n := 0
	for _, p := range names {
		f, err := os.Open(p)
		if err != nil {
			continue
		}
		body, _ := io.ReadAll(io.LimitReader(f, dropboxMaxBody))
		f.Close()
		if text := strings.TrimSpace(string(body)); text != "" {
			send(text)
			n++
		}
		_ = os.Remove(p)
	}
	return n
}

// WatchDropbox forwards texts dropped into dir (for example by the index builder on another
// machine) to the admin group, so long jobs can report that they stopped or finished.
func (n *Notifier) WatchDropbox(ctx context.Context, dir string, log *slog.Logger) {
	if err := os.MkdirAll(dir, 0o775); err != nil {
		log.Error("dropbox directory", "dir", dir, "err", err)
		return
	}
	t := time.NewTicker(dropboxEvery)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			drainDir(dir, func(s string) { n.Send(ctx, s) })
		}
	}
}
