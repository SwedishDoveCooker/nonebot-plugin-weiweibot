package bot

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
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

	"vvbot/internal/lib"
	"vvbot/internal/qq"
)

const (
	accTTL        = 5 * time.Minute
	accMaxShown   = 30
	cooldown      = 1500 * time.Millisecond
	maxUploadSize = 10 << 20
)

const helpText = `使用说明:
/vv 关键字 : 返回匹配关键字的随机图片
/r : 返回一张随机图片
/acc 关键字 : 列出所有匹配的图片, 再发送 /acc 数字 或直接发送数字选择
/help : 显示本说明
@机器人 + 命令 或直接发送命令都可以, 关键字可以用空格分开, 不区分大小写`

type Config struct {
	Groups       map[string]bool // empty means every group
	UploadDir    string
	EnableUpload bool // /upload is off until asked for
}

type accState struct {
	items   []lib.Entry
	expires time.Time
}

type Bot struct {
	api  *qq.Client
	lib  *lib.Holder
	cfg  Config
	log  *slog.Logger
	http *http.Client

	mu       sync.Mutex
	seen     map[string]time.Time
	acc      map[string]accState
	lastSeen map[string]time.Time
}

func New(api *qq.Client, h *lib.Holder, cfg Config, log *slog.Logger) *Bot {
	return &Bot{
		api: api, lib: h, cfg: cfg, log: log,
		http:     &http.Client{Timeout: 30 * time.Second},
		seen:     map[string]time.Time{},
		acc:      map[string]accState{},
		lastSeen: map[string]time.Time{},
	}
}

// HandleEvent is the qq.Handler.
func (b *Bot) HandleEvent(ctx context.Context, typ string, raw json.RawMessage) {
	switch typ {
	case "GROUP_MESSAGE_CREATE", "GROUP_AT_MESSAGE_CREATE", "C2C_MESSAGE_CREATE":
	default:
		return
	}
	var m qq.Message
	if err := json.Unmarshal(raw, &m); err != nil {
		b.log.Warn("bad message payload", "type", typ, "err", err)
		return
	}
	tgt, sender := qq.TargetOf(typ, &m)
	if tgt.Group && len(b.cfg.Groups) > 0 && !b.cfg.Groups[tgt.ID] {
		return
	}
	if b.duplicate(m.ID) {
		return
	}
	text, _ := cleanContent(m.Content)
	cmd, args, isCmd := parseCommand(text)
	key := tgt.ID + "|" + sender

	switch {
	case isCmd:
	case isNumber(text) && b.hasAcc(key):
		cmd, args = "acc", text
	default:
		return // not for us
	}
	if b.throttled(sender) {
		return
	}
	b.log.Info("command", "cmd", cmd, "args", args, "group", tgt.Group, "sender", sender)

	switch cmd {
	case "help":
		b.text(ctx, tgt, m.ID, helpText)
	case "vv":
		b.cmdVV(ctx, tgt, m.ID, args)
	case "r":
		b.cmdRandom(ctx, tgt, m.ID)
	case "acc":
		b.cmdAcc(ctx, tgt, m.ID, key, args)
	case "upload":
		if b.cfg.EnableUpload {
			b.cmdUpload(ctx, tgt, m.ID, m.Attachments)
		}
	}
}

func (b *Bot) duplicate(id string) bool {
	if id == "" {
		return false
	}
	b.mu.Lock()
	defer b.mu.Unlock()
	now := time.Now()
	if len(b.seen) > 4096 {
		for k, t := range b.seen {
			if now.Sub(t) > 10*time.Minute {
				delete(b.seen, k)
			}
		}
	}
	if _, ok := b.seen[id]; ok {
		return true
	}
	b.seen[id] = now
	return false
}

func (b *Bot) throttled(sender string) bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	now := time.Now()
	if len(b.lastSeen) > 4096 {
		for k, t := range b.lastSeen {
			if now.Sub(t) > time.Minute {
				delete(b.lastSeen, k)
			}
		}
	}
	if t, ok := b.lastSeen[sender]; ok && now.Sub(t) < cooldown {
		return true
	}
	b.lastSeen[sender] = now
	return false
}

func (b *Bot) hasAcc(key string) bool {
	b.mu.Lock()
	defer b.mu.Unlock()
	s, ok := b.acc[key]
	return ok && time.Now().Before(s.expires)
}

func (b *Bot) setAcc(key string, items []lib.Entry) {
	b.mu.Lock()
	defer b.mu.Unlock()
	if len(b.acc) > 2048 {
		for k, s := range b.acc {
			if time.Now().After(s.expires) {
				delete(b.acc, k)
			}
		}
	}
	b.acc[key] = accState{items: items, expires: time.Now().Add(accTTL)}
}

func (b *Bot) getAcc(key string) ([]lib.Entry, bool) {
	b.mu.Lock()
	defer b.mu.Unlock()
	s, ok := b.acc[key]
	if !ok || time.Now().After(s.expires) {
		return nil, false
	}
	return s.items, true
}

func (b *Bot) text(ctx context.Context, t qq.Target, msgID, s string) {
	if err := b.api.ReplyText(ctx, t, msgID, s); err != nil {
		b.log.Warn("reply text failed", "err", err)
	}
}

func (b *Bot) image(ctx context.Context, t qq.Target, msgID string, e lib.Entry) {
	data, err := os.ReadFile(e.Path)
	if err != nil {
		b.log.Error("read image", "path", e.Path, "err", err)
		b.text(ctx, t, msgID, "图片读取失败了喵")
		return
	}
	if err := b.api.ReplyImage(ctx, t, msgID, data, ""); err != nil {
		b.log.Warn("reply image failed", "text", e.Text, "err", err)
		if !errors.Is(err, qq.ErrReplyLimit) {
			b.text(ctx, t, msgID, "图片发送失败了喵, 请稍后再试")
		}
	}
}

func (b *Bot) cmdVV(ctx context.Context, t qq.Target, msgID, args string) {
	if args == "" {
		b.text(ctx, t, msgID, "请输入查询参数喵")
		return
	}
	e, ok := lib.Pick(b.lib.Get().Search(args))
	if !ok {
		b.text(ctx, t, msgID, "not found\n请注意, 关键词中的标点符号会被忽略")
		return
	}
	b.image(ctx, t, msgID, e)
}

func (b *Bot) cmdRandom(ctx context.Context, t qq.Target, msgID string) {
	e, ok := b.lib.Get().Random()
	if !ok {
		b.text(ctx, t, msgID, "图库还是空的喵")
		return
	}
	b.image(ctx, t, msgID, e)
}

func (b *Bot) cmdAcc(ctx context.Context, t qq.Target, msgID, key, args string) {
	if args == "" {
		b.text(ctx, t, msgID, "请输入查询参数喵")
		return
	}
	if isNumber(args) {
		items, ok := b.getAcc(key)
		if !ok {
			b.text(ctx, t, msgID, "没有找到相关缓存喵, 请先 /acc 关键字 查询")
			return
		}
		n, _ := strconv.Atoi(args)
		if n < 1 || n > len(items) {
			b.text(ctx, t, msgID, fmt.Sprintf("请输入 1 到 %d 之间的数字喵", len(items)))
			return
		}
		b.image(ctx, t, msgID, items[n-1])
		return
	}
	res := b.lib.Get().Search(args)
	switch len(res) {
	case 0:
		b.text(ctx, t, msgID, "not found\n请注意, 关键词中的标点符号会被忽略")
	case 1:
		b.image(ctx, t, msgID, res[0])
	default:
		shown := res
		if len(shown) > accMaxShown {
			shown = shown[:accMaxShown]
		}
		b.setAcc(key, shown)
		var sb strings.Builder
		sb.WriteString("匹配到多张图片, 请发送数字选择\n")
		for i, e := range shown {
			fmt.Fprintf(&sb, "%d : %s\n", i+1, e.Text)
		}
		if len(res) > len(shown) {
			fmt.Fprintf(&sb, "...还有 %d 条未显示, 请加上更多关键字", len(res)-len(shown))
		}
		b.text(ctx, t, msgID, strings.TrimRight(sb.String(), "\n"))
	}
}

func (b *Bot) cmdUpload(ctx context.Context, t qq.Target, msgID string, atts []qq.Attachment) {
	var saved int
	for _, a := range atts {
		if a.URL == "" || (a.ContentType != "" && !strings.HasPrefix(a.ContentType, "image")) {
			continue
		}
		if err := b.saveUpload(ctx, a); err != nil {
			b.log.Warn("upload failed", "url", a.URL, "err", err)
			continue
		}
		saved++
	}
	if saved == 0 {
		b.text(ctx, t, msgID, "没有找到图片喵, 请在命令里附带图片再试")
		return
	}
	b.text(ctx, t, msgID, fmt.Sprintf("收到 %d 张图片, 谢谢投稿, 审核后入库", saved))
}

func (b *Bot) saveUpload(ctx context.Context, a qq.Attachment) error {
	u := a.URL
	switch {
	case strings.HasPrefix(u, "//"):
		u = "https:" + u
	case !strings.Contains(u, "://"):
		u = "https://" + u
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u, nil)
	if err != nil {
		return err
	}
	resp, err := b.http.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("status %d", resp.StatusCode)
	}
	data, err := io.ReadAll(io.LimitReader(resp.Body, maxUploadSize+1))
	if err != nil {
		return err
	}
	if len(data) > maxUploadSize {
		return errors.New("file too large")
	}
	ext := sniffExt(data)
	if ext == "" {
		return errors.New("not a recognised image")
	}
	sum := sha256.Sum256(data)
	name := hex.EncodeToString(sum[:8]) + ext
	if err := os.MkdirAll(b.cfg.UploadDir, 0o755); err != nil {
		return err
	}
	dst := filepath.Join(b.cfg.UploadDir, name)
	if _, err := os.Stat(dst); err == nil {
		return nil // already have it
	}
	tmp := dst + ".tmp"
	if err := os.WriteFile(tmp, data, 0o644); err != nil {
		return err
	}
	return os.Rename(tmp, dst)
}

func sniffExt(d []byte) string {
	switch ct := http.DetectContentType(d); ct {
	case "image/jpeg":
		return ".jpg"
	case "image/png":
		return ".png"
	case "image/gif":
		return ".gif"
	case "image/webp":
		return ".webp"
	}
	return ""
}
