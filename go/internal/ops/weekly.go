package ops

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	mediaID       = 8726750 // bilibili bangumi md8726750 《这就是中国》
	pollEvery     = 10 * time.Minute
	remindEvery   = 3 * time.Hour
	maxReminders  = 3
	heartbeatEach = time.Minute
	biliUA        = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

// Weekly watches for a new episode, reminds the owner, and takes the cookies needed to fetch it.
type Weekly struct {
	st         *Store
	n          *Notifier
	log        *slog.Logger
	hc         *http.Client
	secretsDir string
	started    time.Time

	// JobsDir is where update jobs are handed to the updater daemon. When empty the OnReady hook
	// is used instead.
	JobsDir string

	// OnReady is called (in a goroutine) when cookies are available and an update should run.
	// It is set by the pipeline integration; while nil the bot only collects cookies.
	OnReady func(ctx context.Context, ep int) error

	mu      sync.Mutex
	authBuf string
	buvid   string
}

func NewWeekly(st *Store, n *Notifier, secretsDir string, log *slog.Logger) *Weekly {
	return &Weekly{st: st, n: n, log: log, hc: &http.Client{Timeout: 20 * time.Second}, secretsDir: secretsDir, started: time.Now()}
}

func (w *Weekly) CookiesPath() string { return filepath.Join(w.secretsDir, "yt_cookies.txt") }

// Start reports an unclean restart (a likely power cut) and records the boot.
func (w *Weekly) Start(ctx context.Context) {
	s := w.st.Get()
	if !s.LastAlive.IsZero() && !s.CleanShutdownAt.After(s.LastAlive) {
		gap := time.Since(s.LastAlive).Round(time.Minute)
		w.n.Send(ctx, fmt.Sprintf("机器人刚启动, 上次不是正常退出: 最后存活 %s, 中断约 %s, 可能是断电或系统重启",
			s.LastAlive.Format("01-02 15:04"), gap))
	}
	_ = w.st.Update(func(s *State) { s.LastAlive = time.Now() })
}

// MarkClean records an orderly shutdown so the next start is not reported as a crash.
func (w *Weekly) MarkClean() {
	_ = w.st.Update(func(s *State) { s.CleanShutdownAt = time.Now().Add(time.Second) })
}

// Run blocks until ctx is done.
func (w *Weekly) Run(ctx context.Context) {
	hb := time.NewTicker(heartbeatEach)
	poll := time.NewTicker(pollEvery)
	defer hb.Stop()
	defer poll.Stop()
	w.check(ctx)
	for {
		select {
		case <-ctx.Done():
			return
		case <-hb.C:
			_ = w.st.Update(func(s *State) { s.LastAlive = time.Now() })
		case <-poll.C:
			w.check(ctx)
		}
	}
}

type reviewResp struct {
	Code   int `json:"code"`
	Result struct {
		Media struct {
			SeasonID int `json:"season_id"`
			NewEp    struct {
				Index string `json:"index"`
			} `json:"new_ep"`
		} `json:"media"`
	} `json:"result"`
}

func (w *Weekly) biliGet(ctx context.Context, url string, out any) error {
	if w.buvid == "" {
		var spi struct {
			Data struct {
				B3 string `json:"b_3"`
				B4 string `json:"b_4"`
			} `json:"data"`
		}
		if err := w.rawGet(ctx, "https://api.bilibili.com/x/frontend/finger/spi", "", &spi); err == nil && spi.Data.B3 != "" {
			w.buvid = "buvid3=" + spi.Data.B3 + "; buvid4=" + spi.Data.B4
		}
	}
	return w.rawGet(ctx, url, w.buvid, out)
}

func (w *Weekly) rawGet(ctx context.Context, url, cookie string, out any) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return err
	}
	req.Header.Set("User-Agent", biliUA)
	req.Header.Set("Referer", "https://www.bilibili.com/")
	if cookie != "" {
		req.Header.Set("Cookie", cookie)
	}
	resp, err := w.hc.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(io.LimitReader(resp.Body, 8<<20))
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("status %d", resp.StatusCode)
	}
	return json.Unmarshal(b, out)
}

// latestEpisode returns the newest episode number and its title.
func (w *Weekly) latestEpisode(ctx context.Context) (int, string, error) {
	var r reviewResp
	if err := w.biliGet(ctx, "https://api.bilibili.com/pgc/review/user?media_id="+strconv.Itoa(mediaID), &r); err != nil {
		return 0, "", err
	}
	if r.Code != 0 {
		return 0, "", fmt.Errorf("bilibili code %d", r.Code)
	}
	ep, err := strconv.Atoi(strings.TrimSpace(r.Result.Media.NewEp.Index))
	if err != nil || ep <= 0 {
		return 0, "", fmt.Errorf("bad episode index %q", r.Result.Media.NewEp.Index)
	}
	title := ""
	var s struct {
		Result struct {
			Episodes []struct {
				ShareCopy string `json:"share_copy"`
			} `json:"episodes"`
		} `json:"result"`
	}
	if err := w.biliGet(ctx, "https://api.bilibili.com/pgc/view/web/season?season_id="+strconv.Itoa(r.Result.Media.SeasonID), &s); err == nil && len(s.Result.Episodes) > 0 {
		title = strings.TrimSpace(s.Result.Episodes[len(s.Result.Episodes)-1].ShareCopy)
	}
	return ep, title, nil
}

func (w *Weekly) check(ctx context.Context) {
	if w.JobsDir != "" {
		for _, ep := range TakeDone(w.JobsDir) {
			w.Done(ep)
		}
	}
	cctx, cancel := context.WithTimeout(ctx, 40*time.Second)
	defer cancel()
	ep, title, err := w.latestEpisode(cctx)
	if err != nil {
		w.log.Warn("episode check failed", "err", err)
		return
	}
	s := w.st.Get()
	switch {
	case s.LastSeenEp == 0:
		_ = w.st.Update(func(s *State) { s.LastSeenEp = ep })
		w.log.Info("baseline episode", "ep", ep)
	case ep > s.LastSeenEp:
		_ = w.st.Update(func(s *State) {
			s.LastSeenEp, s.PendingEp, s.PendingTitle = ep, ep, title
			s.PendingSince, s.RemindCount, s.LastRemind = time.Now(), 0, time.Time{}
		})
		w.remind(ctx)
	case s.PendingEp > 0 && s.RemindCount < maxReminders && time.Since(s.LastRemind) > remindEvery:
		w.remind(ctx)
	}
}

func (w *Weekly) remind(ctx context.Context) {
	s := w.st.Get()
	_ = w.st.Update(func(s *State) { s.RemindCount++; s.LastRemind = time.Now() })
	hint := "请私聊我发送 /auth 加上 YouTube 的 Cookie 开始更新"
	if !s.CookiesSavedAt.IsZero() {
		hint += fmt.Sprintf(", 或发送 /go 使用 %s 保存的 cookies", s.CookiesSavedAt.Format("01-02 15:04"))
	}
	w.n.Send(ctx, fmt.Sprintf("《这就是中国》第 %d 集已更新\n%s\n%s", s.PendingEp, s.PendingTitle, hint))
}

// HandleAuth stores cookies. With appendMode the text is added to what was sent before,
// for cookie strings that are too long for one message.
func (w *Weekly) HandleAuth(ctx context.Context, text string, appendMode bool) string {
	w.mu.Lock()
	defer w.mu.Unlock()
	if appendMode {
		w.authBuf += "; " + strings.TrimSpace(text)
	} else {
		w.authBuf = strings.TrimSpace(text)
	}
	body, names, err := BuildNetscape(w.authBuf, time.Now())
	if err != nil {
		if len(w.authBuf) > 0 && len(names) > 0 {
			return "还不完整: " + err.Error() + "\n如果内容太长发不出去, 可以分几条, 后面的用 /auth+ 追加"
		}
		return "无法识别: " + err.Error()
	}
	if err := os.MkdirAll(w.secretsDir, 0o700); err != nil {
		return "保存失败: " + err.Error()
	}
	if err := WriteFileAtomic(w.CookiesPath(), []byte(body), 0o600); err != nil {
		return "保存失败: " + err.Error()
	}
	w.authBuf = ""
	_ = w.st.Update(func(s *State) { s.CookiesSavedAt = time.Now() })
	return fmt.Sprintf("已保存 %d 个 cookie。%s", len(names), w.startHint(ctx))
}

func (w *Weekly) startHint(ctx context.Context) string {
	s := w.st.Get()
	if s.PendingEp == 0 {
		return "目前没有待更新的新一期。"
	}
	return w.start(ctx, s.PendingEp)
}

func (w *Weekly) start(ctx context.Context, ep int) string {
	if w.JobsDir != "" {
		title := w.st.Get().PendingTitle
		if err := WriteJob(w.JobsDir, Job{Ep: ep, Title: title, RequestedAt: time.Now()}); err != nil {
			return "任务提交失败: " + err.Error()
		}
		return fmt.Sprintf("已提交第 %d 集的更新任务, 更新程序会下载、识别并上线, 完成后在群里通知。", ep)
	}
	if w.OnReady == nil {
		return fmt.Sprintf("第 %d 集的更新流水线还没接入, 先保存 cookies, 接入后会自动使用。", ep)
	}
	go func() {
		if err := w.OnReady(context.WithoutCancel(ctx), ep); err != nil {
			w.log.Error("update run failed", "ep", ep, "err", err)
		}
	}()
	return fmt.Sprintf("开始更新第 %d 集, 完成后会在群里通知。", ep)
}

// Go starts an update with the cookies saved earlier.
func (w *Weekly) Go(ctx context.Context) string {
	s := w.st.Get()
	if s.CookiesSavedAt.IsZero() {
		return "还没有保存过 cookies, 请先 /auth"
	}
	if s.PendingEp == 0 {
		return "目前没有待更新的新一期。"
	}
	return w.start(ctx, s.PendingEp)
}

// Done clears the pending episode after a successful update.
func (w *Weekly) Done(ep int) {
	_ = w.st.Update(func(s *State) {
		if s.PendingEp == ep {
			s.PendingEp, s.PendingTitle, s.RemindCount = 0, "", 0
		}
	})
}

func (w *Weekly) Status() string {
	s := w.st.Get()
	var sb strings.Builder
	fmt.Fprintf(&sb, "已运行 %s\n", time.Since(w.started).Round(time.Minute))
	fmt.Fprintf(&sb, "B 站最新一集: 第 %d 集\n", s.LastSeenEp)
	if s.PendingEp > 0 {
		fmt.Fprintf(&sb, "待更新: 第 %d 集 (已提醒 %d 次)\n", s.PendingEp, s.RemindCount)
	} else {
		sb.WriteString("待更新: 无\n")
	}
	if s.CookiesSavedAt.IsZero() {
		sb.WriteString("cookies: 未保存")
	} else {
		fmt.Fprintf(&sb, "cookies: %s 保存", s.CookiesSavedAt.Format("01-02 15:04"))
	}
	return sb.String()
}
