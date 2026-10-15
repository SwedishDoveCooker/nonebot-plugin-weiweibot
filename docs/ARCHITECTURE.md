# VV 群聊图库机器人: 架构与运维

目标: 在两台无公网的小机器(armbian 与 Jetson)上, 用 QQ 官方机器人提供"台词搜图"。
所有重活(识别、向量化)都在本机完成, 不依赖云服务; 断电后能自己恢复。

## 组成

```
 QQ 官方机器人 (WebSocket, 无需公网)
        │
   ┌────┴─────┐
   │ AstrBot  │  前台: 命令、主动接话。插件 astrbot-plugin/vv_search
   └────┬─────┘
        │ 本机 HTTP  127.0.0.1:8770
   ┌────┴─────────────┐        ┌───────────────────┐
   │ vvbot-ops (Go)   │◄──────►│ vvpipe-embed (Py) │  句向量服务 127.0.0.1:8765
   │ 图库+向量检索     │        └───────────────────┘
   │ 每周新一期提醒    │        ┌───────────────────┐
   │ 任务单 / 群通知   │◄──────►│ vvpipe-daemon(Py) │  更新程序: 收件夹+任务单 → 识别 → 入库
   └──────────────────┘        └───────────────────┘
```

| 服务 | 语言 | 作用 |
|---|---|---|
| `astrbot` | Python | 唯一连接 QQ 的前台。命令: `/help /vv /r /acc`(再发数字)`/auth /authadd /go /status`(后三者仅车主)。不带 @ 的"有没有…表情包"会主动回图 |
| `vvbot-ops` | Go | 图库、向量搜索、本机 HTTP 接口、每周 B 站新一期检测与群提醒、任务单、群通知投递目录。**不连 QQ** |
| `vvpipe-embed` | Python | bge-small-zh ONNX, 把搜索词/字幕变成 512 维向量, 只监听本机 |
| `vvpipe-daemon` | Python | 监视 `data/inbox` 与 `data/jobs`: 视频 → OCR 字幕 + 人脸相似度 → 打包 → 向量 → 上线 → 群里通知 |
| `vvbot` | Go | 旧的 Go 前台(自带命令)。**已停用、不再维护**, 与 AstrBot 互斥, 仅作应急 |

`vv-frontend go|astrbot` 在两个前台之间切换(同一时刻只能有一个连接 QQ)。

## 数据 (armbian, `/mnt/ssd/vvbot/data`)

```
index/entries/epNNNN.jsonl   每期的字幕行(文本、秒数、人脸相似度、包内偏移)
index/frames/epNNNN.pack     每期的 JPEG 打包文件(1080p)
index/vectors/epNNNN.f16     每行一个 512 维 float16 单位向量
inbox/                       放视频进来 → 自动识别(文件名带「第N期」)
jobs/  jobs/done/            机器人写的任务单 / 完成标记
notify/                      任何程序往里放 .txt, 机器人转发到管理群
secrets/yt_cookies.txt       /auth 保存的 cookies (600)
state/state.json             B 站最新一集、待更新、提醒次数、心跳
```

写入都是"先写临时文件, 最后改名": 断电只会得到"整期有"或"整期没有"。机器人加载时会跳过包文件
比索引短、向量文件大小不对的期数, 不会崩溃。

## 每周流程

1. B 站每周二约 10:00 更新, `vvbot-ops` 每 10 分钟检查, 发现新一集 → 在管理群提醒(最多 3 次)。
2. 车主发 `/go`(或先 `/auth` + Cookie) → 写任务单。
3. 更新程序拿到视频后识别约 40 分钟(armbian CPU), 完成后群里通知; 图库 10 分钟内热重载。
4. 下载走本地 SOCKS 代理: armbian 直连 YouTube 不通(GitHub Actions / Worker / Vercel / WARP 也都不行,
   机房 IP 被拦, WARP 的 UDP 出不去)。用户自己的 VLESS+Reality 节点由 Xray 在 `127.0.0.1:10808` 提供。
   - 节点参数放 `/mnt/ssd/xray/node.env`(600, 不进 git; `deploy/bin/v2rayn_to_env.py` 可从 v2rayN 配置生成)。
   - `deploy/bin/setup-xray.sh` 下载 Xray、渲染 `config.json`、启用 `xray.service`、在 `daemon.env` 写 `VV_PROXY`。
   - 更新程序在有 cookies 和 `VV_PROXY` 时才启用 `weekly_fetch.py`, 被 YouTube 拦住时每 30 分钟重试,
     没配置时退回"把视频放进 `inbox/`"。
   - 状态: 配置框架已就绪, 尚未在 armbian 上安装和实测(批量任务一直通过同一节点在电脑上下载)。

## 视频质量

只接受 1080p 以上: 下载器的格式选择里没有低清保底, 下载后用 ffprobe 复核, 识别阶段再拒绝一次,
索引里记录来源高度。曾经因保底逻辑悄悄收下 360p 而全部重做, 这是刻意的防线。

## 本机 HTTP 接口 (127.0.0.1:8770)

`/api/search?q=&k=&mode=list` · `/api/random` · `/api/image?key=` · `/api/health`;
车主接口 `/api/owner/{auth,go,status}` 需要请求头 `X-VV-Token`(`.env` 里的 `VV_API_TOKEN`)。
大模型调用是 OpenAI 兼容接口: `VV_LLM_URL / VV_LLM_KEY / VV_LLM_MODEL`(未配置则只用规则)。

## QQ 的发送限制 (官方文档)

被动回复: 群聊 5 分钟内、每条消息最多 5 次; 单聊 60 分钟、5 次。主动消息文档称已不再提供,
实测在群里开启"机器人主动在群聊内发言"后可发, 因此仅用于周提醒和告警, 失败则排队等下次回复时补发。

## 常用命令 (armbian)

```
systemctl status astrbot vvbot-ops vvpipe-embed vvpipe-daemon
journalctl -u astrbot -n 50 --no-pager
vv-frontend status
/mnt/ssd/vvbot/bin/vvsearch -k 5 "你根本不在乎"      # 在真实数据上试语义搜索
cd /mnt/ssd/vvbot/pipeline && ./.venv/bin/vvpipe embed --index /mnt/ssd/vvbot/data/index   # 补向量
```

## 密钥在哪里 (均不在仓库里)

- `/mnt/ssd/vvbot/.env`: QQ AppID/Secret、群与车主 ID、`VV_API_TOKEN`
- `/mnt/ssd/astrbot/home/data/cmd_config.json`: AstrBot 的 QQ 凭证 (600)
- `/mnt/ssd/astrbot/home/data/vv_plugin.json`: 插件调用接口用的令牌与车主 ID (600)

## 已知限制

- armbian 与 Jetson 访问不了 YouTube, 每周视频要人放进收件夹(见上)。
- 语义搜索的及格线 `VV_SEM_MIN=0.66` 是经验值, 需按实际体验调。
- AstrBot 管理面板只绑定本机, 需要时用 SSH 隧道访问 6185 端口。
- AstrBot 会把群里所有人的消息正文写进 journald 日志(日志在内存里, 重启即清)。
- Jetson 暂未参与: 等换 SD 卡、重装环境后再试 GPU 识别与本地大模型。

## 图片来源 (sources)

索引里每个 id 对应一个来源, 记录在 `index/sources/epNNNN.json` (一个来源一个文件, 多台机器各自添加不会互相覆盖):

| id | 来源 | kind |
|---|---|---|
| 1 - 9999 | 《这就是中国》第 N 期(标题取自 B 站) | `ztjzg` |
| 10000+ | 张维为 B 站账号(mid 1458767615)的视频, 一个视频(分 P 各算一个) 一个 id | `bili` |
| 90000 | 旧的 nonebot-plugin-weiweibot 图片包(1447 张, 没有出处) | `legacy` |

API 的搜索结果带 `detail`(完整出处), AstrBot 插件发图时把它放在图片下面。

### 张维为 B 站账号

- **免登录 1080p**: B 站对游客默认只给 480p, 但网页播放器的"试看"模式用非 wbi 的
  `x/player/playurl?...&try_look=1` 能拿到 1080p DASH。`bili_fetch.py` 直接调用它, 再用 ffmpeg 合并成 mkv,
  所以不需要账号, 也没有 cookie 过期的问题。仍然只收 ≥1080p, 低于就记为 `lowres` 并以后重试。
- **列出全部视频**: 账号空间的列表接口对游客做了风控(-352/412), 改用搜索接口: 以账号名为关键词、
  按 30 天一个时间窗口检索, 只保留 mid 匹配的结果。
- **字幕布局**: 这些视频的硬字幕位置与《这就是中国》一致, 现有的字幕区域和人物识别参数直接可用。
- **存量**: `vvpipe bili-backfill --out ... --work ... --push root@armbian:/mnt/ssd/vvbot/data/index --key ...`,
  状态在 `<work>/bili_state.json`, 可随时停止和继续。
- **每日检查**: 更新程序(`vvpipe daemon --bili-mid 1458767615 --bili-work ...`)约每 20 小时检索一次最近 6 天的视频,
  新的在 armbian 上识别入库, 群里通知。启用前先把电脑上的 `bili_state.json` 拷到 armbian, 避免重复入库。