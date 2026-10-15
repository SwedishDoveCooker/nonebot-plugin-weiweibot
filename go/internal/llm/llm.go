// Package llm is a minimal client for any OpenAI-compatible chat endpoint: the llama.cpp server on
// the Jetson, a cloud API, or a GPU box on the LAN. Which one is only a matter of configuration.
package llm

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"
)

type Client struct {
	url, key, model string
	hc              *http.Client
}

// New returns nil when url is empty, so callers can treat "no model" as a plain nil check.
func New(url, key, model string, timeout time.Duration) *Client {
	if url == "" {
		return nil
	}
	return &Client{url: strings.TrimRight(url, "/"), key: key, model: model, hc: &http.Client{Timeout: timeout}}
}

type message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// Chat sends one system+user exchange and returns the reply text.
func (c *Client) Chat(ctx context.Context, system, user string, maxTokens int) (string, error) {
	if c == nil {
		return "", errors.New("no language model configured")
	}
	body, _ := json.Marshal(map[string]any{
		"model": c.model, "temperature": 0, "max_tokens": maxTokens, "stream": false,
		"messages": []message{{"system", system}, {"user", user}},
	})
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, c.url+"/v1/chat/completions", bytes.NewReader(body))
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", "application/json")
	if c.key != "" {
		req.Header.Set("Authorization", "Bearer "+c.key)
	}
	resp, err := c.hc.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	raw, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("llm: status %d: %.120s", resp.StatusCode, raw)
	}
	var out struct {
		Choices []struct {
			Message message `json:"message"`
		} `json:"choices"`
	}
	if err := json.Unmarshal(raw, &out); err != nil || len(out.Choices) == 0 {
		return "", fmt.Errorf("llm: bad reply: %.120s", raw)
	}
	return strings.TrimSpace(out.Choices[0].Message.Content), nil
}

const extractPrompt = "你是群聊助手。下面是一条群消息,发言者想找一张表情包。" +
	"请只输出他想找的那句台词或关键词本身(不超过 20 个字),不要解释、不要加引号;" +
	"如果消息里没有具体内容,只输出两个字:无。"

// ExtractQuery asks the model which phrase a message is looking for ("" when it names none).
func (c *Client) ExtractQuery(ctx context.Context, text string) (string, error) {
	out, err := c.Chat(ctx, extractPrompt, text, 40)
	if err != nil {
		return "", err
	}
	out = strings.Trim(strings.TrimSpace(out), "\"'“”‘’「」『』《》")
	if i := strings.IndexAny(out, "\r\n"); i >= 0 {
		out = out[:i]
	}
	if r := []rune(out); len(r) > 30 {
		out = string(r[:30])
	}
	if out == "无" || out == "无。" || len([]rune(out)) < 2 {
		return "", nil
	}
	return out, nil
}
