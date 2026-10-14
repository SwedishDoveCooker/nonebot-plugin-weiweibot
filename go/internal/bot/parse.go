// Package bot implements the command layer on top of the qq client and the picture library.
package bot

import (
	"regexp"
	"strings"
)

var (
	mentionRe = regexp.MustCompile(`<@!?[^>]*>`)
	numberRe  = regexp.MustCompile(`^\d{1,3}$`)
)

var aliases = map[string]string{
	"rand":   "r",
	"d":      "acc",
	"上传":     "upload",
	"帮助":     "help",
	"随机":     "r",
	"search": "vv",
}

// cleanContent removes @mentions and surrounding blanks, and normalises a full-width slash.
func cleanContent(s string) (text string, mentioned bool) {
	mentioned = mentionRe.MatchString(s)
	s = mentionRe.ReplaceAllString(s, " ")
	s = strings.TrimSpace(s)
	if strings.HasPrefix(s, "／") {
		s = "/" + strings.TrimPrefix(s, "／")
	}
	return s, mentioned
}

// parseCommand splits "/vv foo bar" into ("vv", "foo bar"). ok is false for non-commands.
func parseCommand(text string) (cmd, args string, ok bool) {
	if !strings.HasPrefix(text, "/") {
		return "", "", false
	}
	rest := strings.TrimSpace(text[1:])
	if rest == "" {
		return "", "", false
	}
	cmd, args, _ = strings.Cut(rest, " ")
	if i := strings.IndexAny(cmd, "\n\t"); i >= 0 {
		args = strings.TrimSpace(cmd[i:] + " " + args)
		cmd = cmd[:i]
	}
	cmd = strings.ToLower(cmd)
	if a, found := aliases[cmd]; found {
		cmd = a
	}
	return cmd, strings.TrimSpace(args), true
}

// isNumber reports whether text is just a small number, optionally the argument of /acc.
func isNumber(text string) bool { return numberRe.MatchString(text) }
