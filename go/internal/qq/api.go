package qq

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"sync"
	"time"
)

const (
	apiBase = "https://api.sgroup.qq.com"
	// QQ allows at most 5 passive replies per incoming message id.
	maxRepliesPerMsg = 5
	// ...and only within a limited window after the message; we stop slightly before it.
	replyWindow = 270 * time.Second
)

// ErrReplyLimit is returned when no passive reply slot is left for a message id.
var ErrReplyLimit = errors.New("qq: passive reply limit reached for this message")

type APIError struct {
	Status  int
	Code    int
	Message string
	TraceID string
}

func (e *APIError) Error() string {
	return fmt.Sprintf("qq api: status=%d code=%d msg=%q trace=%s", e.Status, e.Code, e.Message, e.TraceID)
}

type replyState struct {
	n     int
	first time.Time
}

// Client wraps the REST API. It is safe for concurrent use.
type Client struct {
	ts  *TokenSource
	hc  *http.Client
	log *slog.Logger

	mu      sync.Mutex
	replies map[string]*replyState
}

func NewClient(ts *TokenSource, hc *http.Client, log *slog.Logger) *Client {
	return &Client{ts: ts, hc: hc, log: log, replies: map[string]*replyState{}}
}

// nextSeq reserves the next msg_seq for a passive reply to msgID.
func (c *Client) nextSeq(msgID string) (int, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	now := time.Now()
	if len(c.replies) > 2048 {
		for k, v := range c.replies {
			if now.Sub(v.first) > 10*time.Minute {
				delete(c.replies, k)
			}
		}
	}
	st := c.replies[msgID]
	if st == nil {
		st = &replyState{first: now}
		c.replies[msgID] = st
	}
	if st.n >= maxRepliesPerMsg || now.Sub(st.first) > replyWindow {
		return 0, ErrReplyLimit
	}
	st.n++
	return st.n, nil
}

// RepliesLeft reports how many passive replies remain for msgID.
func (c *Client) RepliesLeft(msgID string) int {
	c.mu.Lock()
	defer c.mu.Unlock()
	st := c.replies[msgID]
	if st == nil {
		return maxRepliesPerMsg
	}
	if time.Since(st.first) > replyWindow {
		return 0
	}
	return maxRepliesPerMsg - st.n
}

func (c *Client) do(ctx context.Context, method, path string, body, out any) error {
	var payload []byte
	if body != nil {
		var err error
		if payload, err = json.Marshal(body); err != nil {
			return err
		}
	}
	var lastErr error
	for attempt := 0; attempt < 3; attempt++ {
		if attempt > 0 {
			select {
			case <-ctx.Done():
				return ctx.Err()
			case <-time.After(time.Duration(attempt) * 800 * time.Millisecond):
			}
		}
		tok, err := c.ts.Get(ctx)
		if err != nil {
			lastErr = err
			continue
		}
		req, err := http.NewRequestWithContext(ctx, method, apiBase+path, bytes.NewReader(payload))
		if err != nil {
			return err
		}
		req.Header.Set("Authorization", "QQBot "+tok)
		req.Header.Set("X-Union-Appid", c.ts.AppID())
		req.Header.Set("Content-Type", "application/json")
		resp, err := c.hc.Do(req)
		if err != nil {
			lastErr = err
			continue
		}
		raw, _ := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
		resp.Body.Close()
		if resp.StatusCode/100 == 2 {
			if out != nil && len(raw) > 0 {
				if err := json.Unmarshal(raw, out); err != nil {
					return fmt.Errorf("decode %s: %w", path, err)
				}
			}
			return nil
		}
		ae := &APIError{Status: resp.StatusCode, TraceID: resp.Header.Get("X-Tps-Trace-Id")}
		var eb struct {
			Message string `json:"message"`
			Code    int    `json:"code"`
			ErrCode int    `json:"err_code"`
		}
		_ = json.Unmarshal(raw, &eb)
		ae.Message, ae.Code = eb.Message, eb.Code
		if ae.Code == 0 {
			ae.Code = eb.ErrCode
		}
		lastErr = ae
		switch {
		case resp.StatusCode == http.StatusUnauthorized:
			c.ts.Invalidate()
		case resp.StatusCode == http.StatusTooManyRequests || resp.StatusCode >= 500:
		default:
			return ae // 4xx: retrying will not help
		}
	}
	return lastErr
}

// Gateway returns the WebSocket URL.
func (c *Client) Gateway(ctx context.Context) (string, error) {
	var out struct {
		URL string `json:"url"`
	}
	if err := c.do(ctx, http.MethodGet, "/gateway", nil, &out); err != nil {
		return "", err
	}
	if out.URL == "" {
		return "", errors.New("empty gateway url")
	}
	return out.URL, nil
}

// ReplyText sends a text passive reply to msgID.
func (c *Client) ReplyText(ctx context.Context, t Target, msgID, text string) error {
	seq, err := c.nextSeq(msgID)
	if err != nil {
		return err
	}
	return c.do(ctx, http.MethodPost, t.base()+"/messages", map[string]any{
		"content": text, "msg_type": 0, "msg_id": msgID, "msg_seq": seq,
	}, nil)
}

// SendActive sends a text message that is not a reply to anything (subject to QQ's active-message quota).
func (c *Client) SendActive(ctx context.Context, t Target, text string) error {
	return c.do(ctx, http.MethodPost, t.base()+"/messages", map[string]any{"content": text, "msg_type": 0}, nil)
}

// ReplyImage uploads image bytes (file_data) and sends them as a passive reply to msgID.
// An optional caption is sent as the message content.
func (c *Client) ReplyImage(ctx context.Context, t Target, msgID string, img []byte, caption string) error {
	var up struct {
		FileInfo string `json:"file_info"`
	}
	if err := c.do(ctx, http.MethodPost, t.base()+"/files", map[string]any{
		"file_type": 1, "file_data": base64.StdEncoding.EncodeToString(img), "srv_send_msg": false,
	}, &up); err != nil {
		return fmt.Errorf("upload image: %w", err)
	}
	seq, err := c.nextSeq(msgID)
	if err != nil {
		return err
	}
	if caption == "" {
		caption = " "
	}
	return c.do(ctx, http.MethodPost, t.base()+"/messages", map[string]any{
		"content": caption, "msg_type": 7, "media": map[string]string{"file_info": up.FileInfo},
		"msg_id": msgID, "msg_seq": seq,
	}, nil)
}
