package bot

import "testing"

func TestCleanAndParse(t *testing.T) {
	cases := []struct {
		in        string
		wantCmd   string
		wantArgs  string
		wantOK    bool
		mentioned bool
	}{
		{"<@57E99FC1> /vv 你好 世界 ", "vv", "你好 世界", true, true},
		{"/vv 你好", "vv", "你好", true, false},
		{"／r", "r", "", true, false},
		{" <@ABC>  /acc 1", "acc", "1", true, true},
		{"/D 诶呀", "acc", "诶呀", true, false},
		{"/上传", "upload", "", true, false},
		{"随便聊聊", "", "", false, false},
		{"/", "", "", false, false},
	}
	for _, c := range cases {
		text, m := cleanContent(c.in)
		cmd, args, ok := parseCommand(text)
		if cmd != c.wantCmd || args != c.wantArgs || ok != c.wantOK || m != c.mentioned {
			t.Errorf("%q -> (%q,%q,%v,%v), want (%q,%q,%v,%v)", c.in, cmd, args, ok, m, c.wantCmd, c.wantArgs, c.wantOK, c.mentioned)
		}
	}
}

func TestIsNumber(t *testing.T) {
	for in, want := range map[string]bool{"1": true, "12": true, "999": true, "1000": false, "a1": false, "": false} {
		if isNumber(in) != want {
			t.Errorf("isNumber(%q) != %v", in, want)
		}
	}
}
