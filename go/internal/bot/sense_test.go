package bot

import (
	"testing"

	"vvbot/internal/lib"
)

func hit(text string, score float32) lib.Scored {
	return lib.Scored{Entry: lib.Entry{Text: text, Norm: lib.Norm(text)}, Score: score}
}

func TestPickScoredDropsWeakMatchesAndDuplicates(t *testing.T) {
	hits := []lib.Scored{
		hit("谢谢大家", 1.0),
		hit("谢谢大家", 1.0), // the same sentence from another episode
		hit("谢谢 大家!", 0.99),
		hit("多谢各位", 0.80),
		hit("今天天气不错", 0.50), // below the floor
	}
	got := pickScored(hits, 10, 0.66, 0)
	if len(got) != 2 || got[0].Text != "谢谢大家" || got[1].Text != "多谢各位" {
		t.Fatalf("got %+v", got)
	}
}

func TestPickScoredWindowKeepsOnlyTheClosest(t *testing.T) {
	hits := []lib.Scored{hit("甲", 0.90), hit("乙", 0.88), hit("丙", 0.70)}
	got := pickScored(hits, 10, 0.66, 0.05)
	if len(got) != 2 {
		t.Fatalf("window should drop 丙, got %+v", got)
	}
}

func TestPickScoredRespectsK(t *testing.T) {
	hits := []lib.Scored{hit("甲", 0.9), hit("乙", 0.8), hit("丙", 0.7)}
	if got := pickScored(hits, 2, 0.66, 0); len(got) != 2 {
		t.Fatalf("k=2 but got %d", len(got))
	}
	if got := pickScored(nil, 2, 0.66, 0); len(got) != 0 {
		t.Fatalf("no hits must give no entries, got %+v", got)
	}
}
