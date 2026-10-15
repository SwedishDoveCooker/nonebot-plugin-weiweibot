// Package proactive decides when a group message is a request for a picture ("有没有群友有那个说
// 「…」的表情包") and what exactly is being looked for. Cheap rules run first; a language model is
// only asked when the rules see a request but cannot find the phrase.
package proactive

import (
	"regexp"
	"strings"
	"sync"
	"time"
)

var (
	ask = regexp.MustCompile(
		`(有没有|谁有|有谁有|求|来个|发个|想要).{0,40}(表情包|表情|梗图|图)` +
			`|(表情包|表情|梗图|图).{0,6}(有吗|有没有|有无|在哪|谁有)`)
	quoted = regexp.MustCompile(`["“'‘「『《](.{2,30}?)["”'’」』》]`)
	said   = regexp.MustCompile(`(?:说|讲|喊|写)[了着]?[:：]?\s*(.{2,30})`)
	noise  = regexp.MustCompile(
		`有没有|有谁有|谁有|群友|这个|那个|就是|之类的|的表情包|表情包|表情|梗图|求|来个|发个|想要|[?？!！。,，~ ]`)
)

// Extract reports whether text asks for a picture, and the phrase to look for ("" when the
// request names nothing searchable, for example "有没有群友有这个表情包").
func Extract(text string) (query string, asks bool) {
	if !ask.MatchString(text) {
		return "", false
	}
	if m := quoted.FindStringSubmatch(text); m != nil {
		return strings.TrimSpace(m[1]), true
	}
	candidate := text
	if m := said.FindStringSubmatch(text); m != nil {
		candidate = m[1]
	}
	candidate = strings.TrimSpace(noise.ReplaceAllString(candidate, ""))
	if len([]rune(candidate)) < 2 {
		return "", true
	}
	return candidate, true
}

// Gate keeps proactive replies from flooding a group: a cooldown between replies and a cap
// per sliding window. QQ also allows at most 5 replies per incoming message.
type Gate struct {
	Cooldown time.Duration
	Max      int
	Window   time.Duration

	mu     sync.Mutex
	recent map[string][]time.Time
}

func NewGate() *Gate {
	return &Gate{Cooldown: 20 * time.Second, Max: 6, Window: 10 * time.Minute, recent: map[string][]time.Time{}}
}

// Allow records and permits a reply in group at now, or refuses it.
func (g *Gate) Allow(group string, now time.Time) bool {
	g.mu.Lock()
	defer g.mu.Unlock()
	keep := g.recent[group][:0]
	for _, t := range g.recent[group] {
		if now.Sub(t) < g.Window {
			keep = append(keep, t)
		}
	}
	if n := len(keep); n > 0 && now.Sub(keep[n-1]) < g.Cooldown {
		g.recent[group] = keep
		return false
	}
	if len(keep) >= g.Max {
		g.recent[group] = keep
		return false
	}
	g.recent[group] = append(keep, now)
	return true
}
