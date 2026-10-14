package ops

import (
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"
)

// BuildNetscape turns either a "Cookie:" header string ("a=1; b=2") or the contents of a Netscape
// cookies.txt into a Netscape cookie file that yt-dlp can read. It returns the file body and the
// sorted cookie names. Only youtube.com / google.com cookies are kept.
func BuildNetscape(input string, now time.Time) (string, []string, error) {
	input = strings.TrimSpace(input)
	if len(input) > 1 && strings.EqualFold(input[:7], "cookie:") {
		input = strings.TrimSpace(input[7:])
	}
	if input == "" {
		return "", nil, errors.New("内容为空")
	}
	var sb strings.Builder
	sb.WriteString("# Netscape HTTP Cookie File\n")
	names := map[string]bool{}

	if strings.Count(input, "\t") >= 6 {
		for _, line := range strings.Split(input, "\n") {
			line = strings.TrimRight(line, "\r")
			if strings.HasPrefix(line, "#HttpOnly_") {
				line = strings.TrimPrefix(line, "#HttpOnly_")
			} else if strings.HasPrefix(line, "#") || strings.TrimSpace(line) == "" {
				continue
			}
			f := strings.Split(line, "\t")
			if len(f) < 7 || !(strings.Contains(f[0], "youtube.com") || strings.Contains(f[0], "google.com")) {
				continue
			}
			names[f[5]] = true
			sb.WriteString(strings.Join(f[:7], "\t") + "\n")
		}
	} else {
		exp := now.Add(180 * 24 * time.Hour).Unix()
		for _, part := range strings.Split(strings.ReplaceAll(input, "\n", ";"), ";") {
			name, val, ok := strings.Cut(strings.TrimSpace(part), "=")
			name = strings.TrimSpace(name)
			if !ok || name == "" || strings.ContainsAny(name, " \t") {
				continue
			}
			names[name] = true
			fmt.Fprintf(&sb, ".youtube.com\tTRUE\t/\tTRUE\t%d\t%s\t%s\n", exp, name, strings.TrimSpace(val))
		}
	}

	list := make([]string, 0, len(names))
	for n := range names {
		list = append(list, n)
	}
	sort.Strings(list)
	if !has(names, "SAPISID", "__Secure-3PAPISID") || !has(names, "SID", "__Secure-3PSID", "__Secure-1PSID") {
		return "", list, fmt.Errorf("缺少登录 cookie, 至少需要 SAPISID(或 __Secure-3PAPISID) 和 __Secure-3PSID(或 SID); 目前收到 %d 个: %s", len(list), strings.Join(list, ", "))
	}
	return sb.String(), list, nil
}

func has(set map[string]bool, any ...string) bool {
	for _, n := range any {
		if set[n] {
			return true
		}
	}
	return false
}
