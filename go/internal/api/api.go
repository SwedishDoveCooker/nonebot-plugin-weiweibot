// Package api is a small local HTTP interface to the picture library and to the owner's
// maintenance commands, so other programs (an agent framework, a script, the AstrBot plugin)
// can use them without touching QQ.
//
//	GET  /api/health                 -> {"ok":true,"lines":N}
//	GET  /api/search?q=TEXT&k=8      -> best matches, literal first (target person first), else by meaning
//	GET  /api/search?q=TEXT&k=30&mode=list -> every literal match, shortest first (what /acc lists)
//	GET  /api/random                 -> one random picture
//	GET  /api/image?key=KEY          -> the JPEG
//	POST /api/owner/auth[?append=1]  body: cookies text   (token required)
//	POST /api/owner/go                                    (token required)
//	GET  /api/owner/status                                (token required)
package api

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"io"
	"net/http"
	"strconv"
	"time"
)

// Result is one search match.
type Result struct {
	Key    string  `json:"key"`
	Text   string  `json:"text"`
	Ep     int     `json:"ep"`
	T      int     `json:"t"`
	Face   float64 `json:"face"`   // similarity to the target person, -1 when unknown
	Score  float32 `json:"score"`  // 1 for literal matches, cosine similarity for semantic ones
	Source string  `json:"source"` // "literal" or "semantic"
	Label  string  `json:"label"`  // text plus episode and time, as shown in lists
}

// Backend is what the API needs from the bot.
type Backend interface {
	Search(ctx context.Context, q string, k int) []Result
	List(ctx context.Context, q string, k int) []Result
	Random() (Result, bool)
	Image(key string) ([]byte, bool)
	Lines() int
}

// Owner is the maintenance side: cookies for the weekly download, starting an update, status.
type Owner interface {
	Auth(ctx context.Context, text string, appendMode bool) string
	Go(ctx context.Context) string
	Status() string
}

// Handler serves the API. Owner endpoints exist only when both o and token are set.
func Handler(b Backend, o Owner, token string) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/health", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, map[string]any{"ok": true, "lines": b.Lines()})
	})
	mux.HandleFunc("/api/search", func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query().Get("q")
		if q == "" {
			http.Error(w, "missing q", http.StatusBadRequest)
			return
		}
		k, _ := strconv.Atoi(r.URL.Query().Get("k"))
		if k < 1 || k > 50 {
			k = 8
		}
		ctx, cancel := context.WithTimeout(r.Context(), 8*time.Second)
		defer cancel()
		var res []Result
		if r.URL.Query().Get("mode") == "list" {
			res = b.List(ctx, q, k)
		} else {
			res = b.Search(ctx, q, k)
		}
		if res == nil {
			res = []Result{}
		}
		writeJSON(w, res)
	})
	mux.HandleFunc("/api/random", func(w http.ResponseWriter, r *http.Request) {
		res, ok := b.Random()
		if !ok {
			http.NotFound(w, r)
			return
		}
		writeJSON(w, res)
	})
	mux.HandleFunc("/api/image", func(w http.ResponseWriter, r *http.Request) {
		data, ok := b.Image(r.URL.Query().Get("key"))
		if !ok {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Type", "image/jpeg")
		w.Header().Set("Cache-Control", "public, max-age=3600")
		_, _ = w.Write(data)
	})

	owner := func(h func(w http.ResponseWriter, r *http.Request)) http.HandlerFunc {
		return func(w http.ResponseWriter, r *http.Request) {
			got := r.Header.Get("X-VV-Token")
			if o == nil || token == "" || subtle.ConstantTimeCompare([]byte(got), []byte(token)) != 1 {
				http.Error(w, "forbidden", http.StatusForbidden)
				return
			}
			h(w, r)
		}
	}
	say := func(w http.ResponseWriter, s string) {
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		_, _ = io.WriteString(w, s)
	}
	mux.HandleFunc("/api/owner/auth", owner(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "POST only", http.StatusMethodNotAllowed)
			return
		}
		body, _ := io.ReadAll(io.LimitReader(r.Body, 64<<10))
		say(w, o.Auth(r.Context(), string(body), r.URL.Query().Get("append") == "1"))
	}))
	mux.HandleFunc("/api/owner/go", owner(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "POST only", http.StatusMethodNotAllowed)
			return
		}
		say(w, o.Go(r.Context()))
	}))
	mux.HandleFunc("/api/owner/status", owner(func(w http.ResponseWriter, r *http.Request) {
		say(w, o.Status())
	}))
	return mux
}

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	_ = json.NewEncoder(w).Encode(v)
}
