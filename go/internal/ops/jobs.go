package ops

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"time"
)

// Job is one "index this episode" request. The bot writes it; the updater daemon on the same
// machine picks it up, and leaves a marker in <dir>/done when the episode is live.
type Job struct {
	Ep          int       `json:"ep"`
	Title       string    `json:"title"`
	RequestedAt time.Time `json:"requested_at"`
}

// WriteJob stores the job as <dir>/epNNNN.json, atomically.
func WriteJob(dir string, j Job) error {
	if err := os.MkdirAll(dir, 0o775); err != nil {
		return err
	}
	b, err := json.MarshalIndent(j, "", "  ")
	if err != nil {
		return err
	}
	return WriteFileAtomic(filepath.Join(dir, fmt.Sprintf("ep%04d.json", j.Ep)), b, 0o664)
}

var doneRe = regexp.MustCompile(`^ep(\d{4})\.json$`)

// TakeDone returns the episodes the daemon finished and removes their markers.
func TakeDone(dir string) []int {
	files, _ := filepath.Glob(filepath.Join(dir, "done", "ep*.json"))
	var eps []int
	for _, f := range files {
		m := doneRe.FindStringSubmatch(filepath.Base(f))
		if m == nil {
			continue
		}
		if n, err := strconv.Atoi(m[1]); err == nil {
			eps = append(eps, n)
		}
		_ = os.Remove(f)
	}
	return eps
}
