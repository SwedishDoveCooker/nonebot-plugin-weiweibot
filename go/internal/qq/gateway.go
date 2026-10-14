package qq

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"sync/atomic"
	"time"

	"github.com/coder/websocket"
)

// IntentGroupAndC2C subscribes to group and C2C events.
const IntentGroupAndC2C = 1 << 25

// Handler receives dispatched events. It is called in its own goroutine.
type Handler func(ctx context.Context, eventType string, data json.RawMessage)

type frame struct {
	Op int             `json:"op"`
	D  json.RawMessage `json:"d"`
	S  int64           `json:"s"`
	T  string          `json:"t"`
}

// Gateway maintains the WebSocket session: identify/resume, heartbeat, reconnect with backoff.
type Gateway struct {
	api     *Client
	ts      *TokenSource
	intents int
	handle  Handler
	log     *slog.Logger

	sessionID string
	seq       atomic.Int64
	lastAck   atomic.Int64 // unix ms of the last heartbeat ack / READY
	ready     atomic.Bool
	onReady   func()
	sem       chan struct{}
}

func NewGateway(api *Client, ts *TokenSource, intents int, h Handler, onReady func(), log *slog.Logger) *Gateway {
	return &Gateway{api: api, ts: ts, intents: intents, handle: h, onReady: onReady, log: log, sem: make(chan struct{}, 16)}
}

// Healthy reports whether the gateway has been acknowledged recently.
func (g *Gateway) Healthy() bool {
	return g.ready.Load() && time.Since(time.UnixMilli(g.lastAck.Load())) < 3*time.Minute
}

// Run blocks until ctx is cancelled, reconnecting forever.
func (g *Gateway) Run(ctx context.Context) {
	backoff := time.Second
	for ctx.Err() == nil {
		started := time.Now()
		err := g.session(ctx)
		g.ready.Store(false)
		if ctx.Err() != nil {
			return
		}
		g.log.Warn("gateway session ended", "err", err)
		if time.Since(started) > time.Minute {
			backoff = time.Second
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(backoff):
		}
		if backoff < 60*time.Second {
			backoff *= 2
		}
	}
}

func (g *Gateway) session(ctx context.Context) error {
	url, err := g.api.Gateway(ctx)
	if err != nil {
		return fmt.Errorf("gateway url: %w", err)
	}
	dctx, cancel := context.WithTimeout(ctx, 20*time.Second)
	conn, _, err := websocket.Dial(dctx, url, nil)
	cancel()
	if err != nil {
		return fmt.Errorf("dial: %w", err)
	}
	conn.SetReadLimit(4 << 20)
	defer conn.CloseNow()

	sctx, stop := context.WithCancel(ctx)
	defer stop()

	send := func(v any) error {
		wctx, c := context.WithTimeout(sctx, 10*time.Second)
		defer c()
		b, _ := json.Marshal(v)
		return conn.Write(wctx, websocket.MessageText, b)
	}

	errc := make(chan error, 1)
	fail := func(err error) {
		select {
		case errc <- err:
		default:
		}
		stop()
	}

	go func() {
		for {
			_, raw, err := conn.Read(sctx)
			if err != nil {
				fail(err)
				return
			}
			var f frame
			if err := json.Unmarshal(raw, &f); err != nil {
				g.log.Warn("bad frame", "err", err)
				continue
			}
			if f.S > 0 {
				g.seq.Store(f.S)
			}
			switch f.Op {
			case 10: // Hello
				var hello struct {
					Interval int `json:"heartbeat_interval"`
				}
				_ = json.Unmarshal(f.D, &hello)
				if hello.Interval <= 0 {
					hello.Interval = 40000
				}
				g.lastAck.Store(time.Now().UnixMilli())
				go g.heartbeat(sctx, time.Duration(hello.Interval)*time.Millisecond, send, fail)
				if err := g.identify(sctx, send); err != nil {
					fail(err)
					return
				}
			case 11: // heartbeat ack
				g.lastAck.Store(time.Now().UnixMilli())
			case 7: // server asks us to reconnect
				fail(errors.New("server requested reconnect"))
				return
			case 9: // invalid session
				g.sessionID = ""
				g.seq.Store(0)
				fail(errors.New("invalid session"))
				return
			case 0:
				g.dispatch(sctx, f)
			}
		}
	}()

	<-sctx.Done()
	select {
	case err := <-errc:
		return err
	default:
		return ctx.Err()
	}
}

func (g *Gateway) identify(ctx context.Context, send func(any) error) error {
	tok, err := g.ts.Get(ctx)
	if err != nil {
		return err
	}
	if g.sessionID != "" {
		g.log.Info("resuming session", "seq", g.seq.Load())
		return send(map[string]any{"op": 6, "d": map[string]any{
			"token": "QQBot " + tok, "session_id": g.sessionID, "seq": g.seq.Load(),
		}})
	}
	return send(map[string]any{"op": 2, "d": map[string]any{
		"token": "QQBot " + tok, "intents": g.intents, "shard": []int{0, 1}, "properties": map[string]string{},
	}})
}

func (g *Gateway) heartbeat(ctx context.Context, every time.Duration, send func(any) error, fail func(error)) {
	t := time.NewTicker(every)
	defer t.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-t.C:
			if time.Since(time.UnixMilli(g.lastAck.Load())) > 2*every+10*time.Second {
				fail(errors.New("heartbeat ack timeout"))
				return
			}
			var d any
			if s := g.seq.Load(); s > 0 {
				d = s
			}
			if err := send(map[string]any{"op": 1, "d": d}); err != nil {
				fail(fmt.Errorf("heartbeat: %w", err))
				return
			}
		}
	}
}

func (g *Gateway) dispatch(ctx context.Context, f frame) {
	switch f.T {
	case "READY":
		var r struct {
			SessionID string `json:"session_id"`
		}
		_ = json.Unmarshal(f.D, &r)
		g.sessionID = r.SessionID
		g.lastAck.Store(time.Now().UnixMilli())
		g.ready.Store(true)
		g.log.Info("gateway ready")
		if g.onReady != nil {
			g.onReady()
		}
		return
	case "RESUMED":
		g.lastAck.Store(time.Now().UnixMilli())
		g.ready.Store(true)
		g.log.Info("gateway resumed")
		return
	}
	select {
	case g.sem <- struct{}{}:
	default:
		g.log.Warn("handler pool full, dropping event", "type", f.T)
		return
	}
	go func() {
		defer func() { <-g.sem }()
		defer func() {
			if r := recover(); r != nil {
				g.log.Error("handler panic", "type", f.T, "panic", r)
			}
		}()
		g.handle(ctx, f.T, f.D)
	}()
}
