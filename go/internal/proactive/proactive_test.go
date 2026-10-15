package proactive

import (
	"testing"
	"time"
)

func TestExtract(t *testing.T) {
	cases := []struct {
		text    string
		query   string
		asks    bool
		comment string
	}{
		{"有没有群友有那个说「你根本不在乎」的表情包", "你根本不在乎", true, "the message from the first trial"},
		{"就是那个说「你根本不在乎」的表情包有吗 有没有", "你根本不在乎", true, "question word after the picture"},
		{"有没有那个说'美国想要垄断'的图", "美国想要垄断", true, "ascii quotes"},
		{"谁有那个说文化自信的表情包", "文化自信", true, "no quotes, a phrase after 说"},
		{"有没有群友有这个表情包", "", true, "asks, but names nothing"},
		{"今天天气不错", "", false, "not a request"},
		{"好像只有", "", false, "chatter"},
		{"我觉得这个说法不对", "", false, "mentions 说 but is not a request"},
		{"", "", false, "empty"},
	}
	for _, c := range cases {
		q, asks := Extract(c.text)
		if q != c.query || asks != c.asks {
			t.Errorf("%s: Extract(%q) = (%q,%v), want (%q,%v)", c.comment, c.text, q, asks, c.query, c.asks)
		}
	}
}

func TestGateCooldownAndWindowCap(t *testing.T) {
	g := NewGate()
	t0 := time.Unix(1_700_000_000, 0)
	if !g.Allow("a", t0) {
		t.Fatal("first reply must be allowed")
	}
	if g.Allow("a", t0.Add(5*time.Second)) {
		t.Fatal("inside the cooldown must be refused")
	}
	if !g.Allow("b", t0.Add(5*time.Second)) {
		t.Fatal("another group has its own cooldown")
	}
	now := t0
	allowed := 1
	for i := 0; i < 20; i++ {
		now = now.Add(25 * time.Second)
		if g.Allow("a", now) {
			allowed++
		}
	}
	if allowed != g.Max {
		t.Fatalf("a 10 minute window must cap replies at %d, got %d", g.Max, allowed)
	}
	if !g.Allow("a", now.Add(11*time.Minute)) {
		t.Fatal("after the window the group may be answered again")
	}
}
