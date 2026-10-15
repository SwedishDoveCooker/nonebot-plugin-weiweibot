package api

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

type fake struct{}

func (fake) Search(_ context.Context, q string, k int) []Result {
	if q == "none" {
		return nil
	}
	return []Result{{Key: "e1-0", Text: q, Ep: 1, Score: 1, Source: "literal"}}
}

func (fake) List(_ context.Context, q string, k int) []Result {
	return []Result{{Key: "a", Text: "短"}, {Key: "b", Text: "长一点"}}
}

func (fake) Random() (Result, bool) { return Result{Key: "e1-0", Text: "随机"}, true }

func (fake) Image(key string) ([]byte, bool) {
	if key == "e1-0" {
		return []byte("\xff\xd8jpeg\xff\xd9"), true
	}
	return nil, false
}

func (fake) Lines() int { return 42 }

type fakeOwner struct{ got []string }

func (f *fakeOwner) Auth(_ context.Context, text string, appendMode bool) string {
	f.got = append(f.got, "auth:"+text)
	if appendMode {
		return "appended"
	}
	return "saved"
}
func (f *fakeOwner) Go(context.Context) string { return "started" }
func (f *fakeOwner) Status() string            { return "ok" }

func do(h http.Handler, method, path, body, token string) *httptest.ResponseRecorder {
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	if token != "" {
		req.Header.Set("X-VV-Token", token)
	}
	h.ServeHTTP(rec, req)
	return rec
}

func TestSearchListRandomImageHealth(t *testing.T) {
	h := Handler(fake{}, nil, "")
	var got []Result
	if err := json.Unmarshal(do(h, "GET", "/api/search?q=你好", "", "").Body.Bytes(), &got); err != nil || len(got) != 1 || got[0].Text != "你好" {
		t.Fatalf("got %+v err=%v", got, err)
	}
	if body := do(h, "GET", "/api/search?q=none", "", "").Body.String(); body != "[]\n" {
		t.Fatalf("empty result must be [], got %q", body)
	}
	if do(h, "GET", "/api/search", "", "").Code != http.StatusBadRequest {
		t.Fatal("missing q must be a 400")
	}
	var list []Result
	_ = json.Unmarshal(do(h, "GET", "/api/search?q=x&mode=list&k=30", "", "").Body.Bytes(), &list)
	if len(list) != 2 || list[0].Key != "a" {
		t.Fatalf("list mode = %+v", list)
	}
	var rnd Result
	_ = json.Unmarshal(do(h, "GET", "/api/random", "", "").Body.Bytes(), &rnd)
	if rnd.Text != "随机" {
		t.Fatalf("random = %+v", rnd)
	}
	rec := do(h, "GET", "/api/image?key=e1-0", "", "")
	if rec.Code != 200 || rec.Header().Get("Content-Type") != "image/jpeg" {
		t.Fatalf("image: %d %s", rec.Code, rec.Header().Get("Content-Type"))
	}
	if do(h, "GET", "/api/image?key=nope", "", "").Code != http.StatusNotFound {
		t.Fatal("unknown key must be a 404")
	}
	var health map[string]any
	_ = json.Unmarshal(do(h, "GET", "/api/health", "", "").Body.Bytes(), &health)
	if health["lines"].(float64) != 42 {
		t.Fatalf("health = %v", health)
	}
}

func TestOwnerEndpointsNeedTheToken(t *testing.T) {
	o := &fakeOwner{}
	h := Handler(fake{}, o, "s3cret")
	if do(h, "POST", "/api/owner/auth", "cookie", "").Code != http.StatusForbidden {
		t.Fatal("no token must be refused")
	}
	if do(h, "POST", "/api/owner/auth", "cookie", "wrong").Code != http.StatusForbidden {
		t.Fatal("wrong token must be refused")
	}
	if len(o.got) != 0 {
		t.Fatal("a refused request must not reach the owner")
	}
	if rec := do(h, "POST", "/api/owner/auth", "a=1", "s3cret"); rec.Body.String() != "saved" {
		t.Fatalf("auth = %q", rec.Body.String())
	}
	if rec := do(h, "POST", "/api/owner/auth?append=1", "b=2", "s3cret"); rec.Body.String() != "appended" {
		t.Fatalf("append = %q", rec.Body.String())
	}
	if do(h, "GET", "/api/owner/auth", "", "s3cret").Code != http.StatusMethodNotAllowed {
		t.Fatal("auth must be POST only")
	}
	if rec := do(h, "POST", "/api/owner/go", "", "s3cret"); rec.Body.String() != "started" {
		t.Fatalf("go = %q", rec.Body.String())
	}
	if rec := do(h, "GET", "/api/owner/status", "", "s3cret"); rec.Body.String() != "ok" {
		t.Fatalf("status = %q", rec.Body.String())
	}
}

func TestOwnerEndpointsAreOffWithoutATokenOrOwner(t *testing.T) {
	if do(Handler(fake{}, &fakeOwner{}, ""), "GET", "/api/owner/status", "", "").Code != http.StatusForbidden {
		t.Fatal("an empty token must disable the owner endpoints")
	}
	if do(Handler(fake{}, nil, "x"), "GET", "/api/owner/status", "", "x").Code != http.StatusForbidden {
		t.Fatal("no owner must disable the owner endpoints")
	}
}
