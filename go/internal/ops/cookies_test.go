package ops

import (
	"strings"
	"testing"
	"time"
)

func TestBuildNetscapeHeader(t *testing.T) {
	in := "Cookie: SID=a; __Secure-3PSID=b; SAPISID=c; __Secure-3PAPISID=d; YSC=e"
	body, names, err := BuildNetscape(in, time.Unix(1_700_000_000, 0))
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(body, "# Netscape HTTP Cookie File\n") || !strings.Contains(body, "\tSAPISID\tc\n") {
		t.Fatalf("bad body: %q", body)
	}
	if len(names) != 5 {
		t.Fatalf("names = %v", names)
	}
}

func TestBuildNetscapeMissing(t *testing.T) {
	if _, _, err := BuildNetscape("YSC=e; PREF=f", time.Now()); err == nil {
		t.Fatal("expected an error for a cookie set without login cookies")
	}
}

func TestBuildNetscapeFile(t *testing.T) {
	in := "# Netscape HTTP Cookie File\n" +
		".youtube.com\tTRUE\t/\tTRUE\t1900000000\tSAPISID\tc\n" +
		"#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t1900000000\t__Secure-3PSID\tb\n" +
		".example.com\tTRUE\t/\tTRUE\t1900000000\tOTHER\tx\n"
	body, names, err := BuildNetscape(in, time.Now())
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(body, "OTHER") || len(names) != 2 {
		t.Fatalf("foreign cookie leaked or names wrong: %v %q", names, body)
	}
}
