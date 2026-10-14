// Package ops holds the operational side of the bot: persistent state, notifications to the
// admin group, cookie intake and the weekly "new episode" watcher.
package ops

import (
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"sync"
	"time"
)

// State is everything that must survive a restart or a power cut.
type State struct {
	LastSeenEp      int       `json:"last_seen_ep"`      // newest episode number seen on bilibili
	PendingEp       int       `json:"pending_ep"`        // episode waiting for an update run
	PendingTitle    string    `json:"pending_title"`     //
	PendingSince    time.Time `json:"pending_since"`     //
	RemindCount     int       `json:"remind_count"`      // reminders sent for PendingEp
	LastRemind      time.Time `json:"last_remind"`       //
	CookiesSavedAt  time.Time `json:"cookies_saved_at"`  //
	LastAlive       time.Time `json:"last_alive"`        // heartbeat, used to report unclean restarts
	CleanShutdownAt time.Time `json:"clean_shutdown_at"` //
}

// Store keeps State in a JSON file and writes it atomically (temp file, fsync, rename).
type Store struct {
	path string
	mu   sync.Mutex
	s    State
}

func OpenStore(path string) (*Store, error) {
	st := &Store{path: path}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return nil, err
	}
	b, err := os.ReadFile(path)
	switch {
	case errors.Is(err, os.ErrNotExist):
	case err != nil:
		return nil, err
	default:
		if err := json.Unmarshal(b, &st.s); err != nil {
			// A torn or corrupt file must not keep the bot from starting.
			_ = os.Rename(path, path+".corrupt")
			st.s = State{}
		}
	}
	return st, nil
}

func (s *Store) Get() State {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.s
}

// Update applies f and persists the result.
func (s *Store) Update(f func(*State)) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	f(&s.s)
	return s.writeLocked()
}

func (s *Store) writeLocked() error {
	b, err := json.MarshalIndent(s.s, "", "  ")
	if err != nil {
		return err
	}
	return WriteFileAtomic(s.path, b, 0o644)
}

// WriteFileAtomic writes data to path so that a power cut leaves either the old or the new content.
func WriteFileAtomic(path string, data []byte, perm os.FileMode) error {
	dir := filepath.Dir(path)
	f, err := os.CreateTemp(dir, filepath.Base(path)+".tmp*")
	if err != nil {
		return err
	}
	tmp := f.Name()
	cleanup := func() { _ = os.Remove(tmp) }
	if _, err := f.Write(data); err != nil {
		f.Close()
		cleanup()
		return err
	}
	if err := f.Chmod(perm); err != nil {
		f.Close()
		cleanup()
		return err
	}
	if err := f.Sync(); err != nil {
		f.Close()
		cleanup()
		return err
	}
	if err := f.Close(); err != nil {
		cleanup()
		return err
	}
	if err := os.Rename(tmp, path); err != nil {
		cleanup()
		return err
	}
	if d, err := os.Open(dir); err == nil {
		_ = d.Sync()
		d.Close()
	}
	return nil
}
