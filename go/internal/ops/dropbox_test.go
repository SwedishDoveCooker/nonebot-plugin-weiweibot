package ops

import (
	"os"
	"path/filepath"
	"testing"
)

func TestDrainDir(t *testing.T) {
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, "b.txt"), []byte("second\n"), 0o644)
	os.WriteFile(filepath.Join(dir, "a.txt"), []byte("  first  "), 0o644)
	os.WriteFile(filepath.Join(dir, "c.txt.tmp"), []byte("still writing"), 0o644)
	os.WriteFile(filepath.Join(dir, "empty.txt"), []byte("   \n"), 0o644)

	var got []string
	n := drainDir(dir, func(s string) { got = append(got, s) })

	if n != 2 || len(got) != 2 || got[0] != "first" || got[1] != "second" {
		t.Fatalf("n=%d got=%q", n, got)
	}
	if _, err := os.Stat(filepath.Join(dir, "a.txt")); !os.IsNotExist(err) {
		t.Fatal("delivered file must be removed")
	}
	if _, err := os.Stat(filepath.Join(dir, "c.txt.tmp")); err != nil {
		t.Fatal("a file that is still being written must be left alone")
	}
}
