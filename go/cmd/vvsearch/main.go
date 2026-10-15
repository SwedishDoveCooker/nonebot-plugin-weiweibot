// Command vvsearch runs one semantic query against an index directory, for debugging and timing.
package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"strings"
	"time"

	"vvbot/internal/lib"
	"vvbot/internal/sem"
)

func main() {
	index := flag.String("index", "/mnt/ssd/vvbot/data/index", "index directory")
	url := flag.String("embed", "http://127.0.0.1:8765", "embedding service")
	k := flag.Int("k", 8, "number of results")
	flag.Parse()
	q := strings.Join(flag.Args(), " ")
	if q == "" {
		fmt.Fprintln(os.Stderr, "usage: vvsearch [-index DIR] [-k N] QUERY")
		os.Exit(2)
	}

	t0 := time.Now()
	entries, vec, skipped, err := lib.LoadIndex(*index)
	if err != nil {
		fmt.Fprintln(os.Stderr, "load:", err)
		os.Exit(1)
	}
	l := lib.NewWithVec(entries, vec)
	fmt.Printf("loaded %d lines, %d vectors in %v (%d episodes skipped)\n",
		len(entries), vec.Rows(), time.Since(t0).Round(time.Millisecond), len(skipped))

	t1 := time.Now()
	v, err := sem.New(*url).Embed(context.Background(), q)
	if err != nil {
		fmt.Fprintln(os.Stderr, "embed:", err)
		os.Exit(1)
	}
	t2 := time.Now()
	hits := l.Semantic(v, *k)
	t3 := time.Now()
	fmt.Printf("embed %v, scan %v over %d rows\n", t2.Sub(t1).Round(time.Millisecond),
		t3.Sub(t2).Round(time.Millisecond), vec.Rows())
	for _, h := range hits {
		fmt.Printf("  %.3f  %s\n", h.Score, h.Entry.Label())
	}
}
