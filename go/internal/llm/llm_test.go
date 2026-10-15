package llm

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func fakeServer(t *testing.T, reply string, status int) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/chat/completions" || r.Header.Get("Authorization") != "Bearer k" {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		w.WriteHeader(status)
		_ = json.NewEncoder(w).Encode(map[string]any{
			"choices": []map[string]any{{"message": map[string]string{"role": "assistant", "content": reply}}},
		})
	}))
}

func TestExtractQueryCleansTheModelAnswer(t *testing.T) {
	for _, c := range []struct{ reply, want string }{
		{"「你根本不在乎」", "你根本不在乎"},
		{"  文化自信\n(以上是提取结果)", "文化自信"},
		{"无", ""},
		{"好", ""},
	} {
		s := fakeServer(t, c.reply, 200)
		got, err := New(s.URL, "k", "m", 2*time.Second).ExtractQuery(context.Background(), "x")
		s.Close()
		if err != nil || got != c.want {
			t.Errorf("reply %q -> %q, %v; want %q", c.reply, got, err, c.want)
		}
	}
}

func TestNoModelAndServerErrors(t *testing.T) {
	if New("", "", "", time.Second) != nil {
		t.Fatal("an empty URL must mean no model (nil client)")
	}
	var none *Client
	if _, err := none.ExtractQuery(context.Background(), "x"); err == nil {
		t.Fatal("a nil client must return an error, not panic")
	}
	s := fakeServer(t, "x", 500)
	defer s.Close()
	if _, err := New(s.URL, "k", "m", time.Second).ExtractQuery(context.Background(), "x"); err == nil {
		t.Fatal("a 500 must surface as an error")
	}
}
