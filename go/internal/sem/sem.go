// Package sem turns a search phrase into a sentence vector by asking the local embedding
// service (vvpipe embed-serve). The model lives in that service so the bot stays a small Go
// binary, and so the very same model builds the index and answers the queries.
package sem

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"time"
)

type Client struct {
	url string
	hc  *http.Client
}

func New(url string) *Client {
	return &Client{url: url, hc: &http.Client{Timeout: 4 * time.Second}}
}

// Embed returns the unit-length vector of text.
func (c *Client) Embed(ctx context.Context, text string) ([]float32, error) {
	if c == nil || c.url == "" {
		return nil, errors.New("no embedding service configured")
	}
	body, _ := json.Marshal(map[string][]string{"texts": {text}})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.url+"/embed", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	resp, err := c.hc.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("embedding service: status %d: %.100s", resp.StatusCode, raw)
	}
	var out struct {
		Vecs [][]float32 `json:"vecs"`
	}
	if err := json.Unmarshal(raw, &out); err != nil || len(out.Vecs) != 1 {
		return nil, fmt.Errorf("embedding service: bad reply: %.100s", raw)
	}
	return out.Vecs[0], nil
}
