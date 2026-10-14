// Package sdnotify speaks the minimal systemd notify protocol (READY / WATCHDOG).
package sdnotify

import (
	"net"
	"os"
	"strconv"
	"time"
)

// Send writes one state string to $NOTIFY_SOCKET. It is a no-op outside systemd.
func Send(state string) {
	path := os.Getenv("NOTIFY_SOCKET")
	if path == "" {
		return
	}
	if path[0] == '@' {
		path = "\x00" + path[1:]
	}
	c, err := net.DialUnix("unixgram", nil, &net.UnixAddr{Name: path, Net: "unixgram"})
	if err != nil {
		return
	}
	defer c.Close()
	_, _ = c.Write([]byte(state))
}

// WatchdogInterval returns half of WatchdogSec, or 0 when the watchdog is off.
func WatchdogInterval() time.Duration {
	us, err := strconv.ParseInt(os.Getenv("WATCHDOG_USEC"), 10, 64)
	if err != nil || us <= 0 {
		return 0
	}
	return time.Duration(us) * time.Microsecond / 2
}
