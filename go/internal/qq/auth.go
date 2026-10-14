// Package qq is a small client for the QQ official bot platform (WebSocket gateway + REST v2).
package qq

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"sync"
	"time"
)

const tokenURL = "https://bots.qq.com/app/getAppAccessToken"

// TokenSource caches the app access token and refreshes it shortly before it expires.
type TokenSource struct {
	appID, secret string
	hc            *http.Client

	mu  sync.Mutex
	tok string
	exp time.Time
}

func NewTokenSource(appID, secret string, hc *http.Client) *TokenSource {
	return &TokenSource{appID: appID, secret: secret, hc: hc}
}

func (t *TokenSource) AppID() string { return t.appID }

func (t *TokenSource) Get(ctx context.Context) (string, error) {
	t.mu.Lock()
	defer t.mu.Unlock()
	if t.tok != "" && time.Until(t.exp) > 90*time.Second {
		return t.tok, nil
	}
	body, _ := json.Marshal(map[string]string{"appId": t.appID, "clientSecret": t.secret})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, tokenURL, bytes.NewReader(body))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := t.hc.Do(req)
	if err != nil {
		return "", fmt.Errorf("token request: %w", err)
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<16))
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("token request: status %d: %s", resp.StatusCode, raw)
	}
	var out struct {
		AccessToken string          `json:"access_token"`
		ExpiresIn   json.RawMessage `json:"expires_in"`
	}
	if err := json.Unmarshal(raw, &out); err != nil || out.AccessToken == "" {
		return "", fmt.Errorf("token response invalid: %s", raw)
	}
	secs, _ := strconv.Atoi(string(bytes.Trim(out.ExpiresIn, `"`)))
	if secs <= 0 {
		secs = 300
	}
	t.tok = out.AccessToken
	t.exp = time.Now().Add(time.Duration(secs) * time.Second)
	return t.tok, nil
}

// Invalidate forces the next Get to fetch a new token.
func (t *TokenSource) Invalidate() {
	t.mu.Lock()
	t.tok, t.exp = "", time.Time{}
	t.mu.Unlock()
}
