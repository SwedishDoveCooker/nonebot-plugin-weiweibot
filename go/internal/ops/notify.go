package ops

import (
	"context"
	"log/slog"
	"strings"
	"sync"
	"time"

	"vvbot/internal/qq"
)

const (
	maxActivePerHour = 6
	maxActivePerDay  = 16
	dedupeWindow     = 30 * time.Minute
	outboxCap        = 20
)

// Notifier sends operational messages to one admin group. QQ limits active (non-reply)
// messages, so sends are rate limited, and anything that cannot go out is kept and
// delivered as a passive reply the next time someone speaks in that group.
type Notifier struct {
	api   *qq.Client
	group qq.Target
	log   *slog.Logger

	mu     sync.Mutex
	recent map[string]time.Time
	sent   []time.Time
	outbox []string
}

// NewNotifier is created before the logger and API client (the logger forwards errors
// through it), so those are attached afterwards with Bind.
func NewNotifier(groupOpenID string) *Notifier {
	return &Notifier{group: qq.Target{Group: true, ID: groupOpenID}, recent: map[string]time.Time{}}
}

func (n *Notifier) Bind(api *qq.Client, log *slog.Logger) {
	n.mu.Lock()
	n.api, n.log = api, log
	n.mu.Unlock()
}

func (n *Notifier) Enabled() bool {
	if n == nil || n.group.ID == "" {
		return false
	}
	n.mu.Lock()
	defer n.mu.Unlock()
	return n.api != nil
}

func (n *Notifier) GroupID() string {
	if n == nil {
		return ""
	}
	return n.group.ID
}

func (n *Notifier) allow(msg string) bool {
	now := time.Now()
	if t, ok := n.recent[msg]; ok && now.Sub(t) < dedupeWindow {
		return false
	}
	n.recent[msg] = now
	for k, t := range n.recent {
		if now.Sub(t) > dedupeWindow {
			delete(n.recent, k)
		}
	}
	return true
}

func (n *Notifier) budget() bool {
	now := time.Now()
	keep := n.sent[:0]
	hour, day := 0, 0
	for _, t := range n.sent {
		if now.Sub(t) < 24*time.Hour {
			keep = append(keep, t)
			day++
			if now.Sub(t) < time.Hour {
				hour++
			}
		}
	}
	n.sent = keep
	return hour < maxActivePerHour && day < maxActivePerDay
}

// Send delivers msg to the admin group (identical messages within 30 minutes are dropped).
func (n *Notifier) Send(ctx context.Context, msg string) {
	if !n.Enabled() {
		return
	}
	n.mu.Lock()
	if !n.allow(msg) {
		n.mu.Unlock()
		return
	}
	ok := n.budget()
	if ok {
		n.sent = append(n.sent, time.Now())
	}
	n.mu.Unlock()

	if ok {
		sctx, cancel := context.WithTimeout(ctx, 20*time.Second)
		defer cancel()
		err := n.api.SendActive(sctx, n.group, msg)
		if err == nil {
			return
		}
		n.log.Warn("active notify failed, queued for next reply", "err", err)
	}
	n.mu.Lock()
	if len(n.outbox) >= outboxCap {
		n.outbox = n.outbox[1:]
	}
	n.outbox = append(n.outbox, msg)
	n.mu.Unlock()
}

// Flush delivers queued messages as a passive reply to msgID, which must come from the admin group.
func (n *Notifier) Flush(ctx context.Context, msgID string) {
	if !n.Enabled() {
		return
	}
	n.mu.Lock()
	if len(n.outbox) == 0 {
		n.mu.Unlock()
		return
	}
	text := strings.Join(n.outbox, "\n----\n")
	n.outbox = nil
	n.mu.Unlock()
	if err := n.api.ReplyText(ctx, n.group, msgID, "积压通知:\n"+text); err != nil {
		n.log.Warn("flush outbox failed", "err", err)
		n.mu.Lock()
		n.outbox = append([]string{text}, n.outbox...)
		n.mu.Unlock()
	}
}

// LogHandler wraps a slog.Handler and forwards ERROR records to the admin group.
type LogHandler struct {
	slog.Handler
	n *Notifier
}

func WrapLogHandler(h slog.Handler, n *Notifier) slog.Handler { return &LogHandler{Handler: h, n: n} }

func (h *LogHandler) Handle(ctx context.Context, r slog.Record) error {
	if r.Level >= slog.LevelError && h.n.Enabled() {
		var sb strings.Builder
		sb.WriteString("[ERROR] " + r.Message)
		r.Attrs(func(a slog.Attr) bool {
			s := a.Value.String()
			if len(s) > 120 {
				s = s[:120] + "..."
			}
			sb.WriteString(" " + a.Key + "=" + s)
			return true
		})
		go h.n.Send(context.WithoutCancel(ctx), sb.String())
	}
	return h.Handler.Handle(ctx, r)
}

func (h *LogHandler) WithAttrs(a []slog.Attr) slog.Handler {
	return &LogHandler{Handler: h.Handler.WithAttrs(a), n: h.n}
}

func (h *LogHandler) WithGroup(name string) slog.Handler {
	return &LogHandler{Handler: h.Handler.WithGroup(name), n: h.n}
}
