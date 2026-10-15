package ops

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestWriteJobAndTakeDone(t *testing.T) {
	dir := t.TempDir()
	if err := WriteJob(dir, Job{Ep: 353, Title: "测试", RequestedAt: time.Now()}); err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(filepath.Join(dir, "ep0353.json")); err != nil {
		t.Fatalf("job file missing: %v", err)
	}
	// Writing the same job again must not fail or leave temp files behind.
	if err := WriteJob(dir, Job{Ep: 353, Title: "测试", RequestedAt: time.Now()}); err != nil {
		t.Fatal(err)
	}
	if left, _ := filepath.Glob(filepath.Join(dir, "*.tmp*")); len(left) != 0 {
		t.Fatalf("temp files left: %v", left)
	}

	os.MkdirAll(filepath.Join(dir, "done"), 0o755)
	os.WriteFile(filepath.Join(dir, "done", "ep0353.json"), []byte("{}"), 0o644)
	os.WriteFile(filepath.Join(dir, "done", "notes.txt"), []byte("x"), 0o644)
	got := TakeDone(dir)
	if len(got) != 1 || got[0] != 353 {
		t.Fatalf("TakeDone = %v", got)
	}
	if again := TakeDone(dir); len(again) != 0 {
		t.Fatalf("markers must be consumed, got %v", again)
	}
}
