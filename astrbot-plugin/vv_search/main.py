"""AstrBot front-end for the VV picture bot.

Everything that matters (the picture library, the vectors, the weekly update, the notifications)
lives in the Go services on the same machine. This plugin only speaks QQ through AstrBot and
calls their local HTTP API (127.0.0.1:8770), so either front-end can hold the QQ connection.

Commands: /help /vv /r /acc (then a number) and, for the owner, /auth /authadd /go /status.
Without being addressed it answers "有没有群友有那个说「…」的表情包"-style requests.
"""

from __future__ import annotations

import json
import os
import re
import time

import aiohttp

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star

CONFIG = os.environ.get("VV_PLUGIN_CONFIG", "/mnt/ssd/astrbot/home/data/vv_plugin.json")
TMP = os.environ.get("VV_TMP", "/mnt/ssd/astrbot/home/data/temp")
COOLDOWN_S = 20
ACC_TTL_S = 300
ACC_MAX = 30

HELP = """使用说明:
/vv 关键字 : 返回匹配关键字的随机图片, 没有字面匹配时会按意思找
/r : 返回一张随机图片
/acc 关键字 : 列出所有匹配的图片, 再发送 /acc 数字 或直接发送数字选择
/help : 显示本说明
@机器人 + 命令 或直接发送命令都可以, 关键字可以用空格分开, 不区分大小写"""

# "有没有群友有那个说「你根本不在乎」的表情包", "谁有那个说「…」的图", ...
ASK = re.compile(
    r"(有没有|谁有|有谁有|求|来个|发个|想要).{0,40}(表情包|表情|梗图|图)"
    r"|(表情包|表情|梗图|图).{0,6}(有吗|有没有|有无|在哪|谁有)"
)
QUOTED = re.compile(r"[\"“'‘「『《](.{2,30}?)[\"”'’」』》]")
SAID = re.compile(r"(?:说|讲|喊|写)[了着]?[:：]?\s*(.{2,30})")
NOISE = re.compile(
    r"有没有|有谁有|谁有|群友|这个|那个|就是|之类的|的表情包|表情包|表情|梗图|求|来个|发个|想要|[?？!！。,，~ ]"
)


def extract_query(text: str) -> str | None:
    """The phrase to look for, or None when the message is not asking for a picture."""
    if not ASK.search(text):
        return None
    m = QUOTED.search(text)
    if m:
        return m.group(1).strip()
    m = SAID.search(text)
    candidate = m.group(1) if m else text
    candidate = NOISE.sub("", candidate).strip()
    return candidate if len(candidate) >= 2 else None


def rest(text: str, *names: str) -> str:
    """What follows the command word, whether or not the platform already removed it."""
    m = re.match(r"^\s*[/／]?\s*(?:" + "|".join(map(re.escape, names)) + r")(?=\s|$)\s*", text, re.I)
    return (text[m.end() :] if m else text).strip()


class VVSearch(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self._last: dict[str, float] = {}
        self._pending: dict[str, tuple[float, list[dict]]] = {}
        try:
            with open(CONFIG, encoding="utf-8-sig") as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            cfg = {}
            logger.warning(f"vv_search: no usable config at {CONFIG}; owner commands are disabled")
        self.api = cfg.get("api", "http://127.0.0.1:8770")
        self.token = cfg.get("token", "")
        self.owners = set(cfg.get("owners", []))
        os.makedirs(TMP, exist_ok=True)

    # ---- helpers -------------------------------------------------------------------------
    async def _json(self, path: str, **params):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
            async with s.get(f"{self.api}{path}", params=params) as r:
                if r.status != 200:
                    return None
                return await r.json()

    async def _image_path(self, key: str) -> str | None:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
            async with s.get(f"{self.api}/api/image", params={"key": key}) as r:
                if r.status != 200:
                    return None
                data = await r.read()
        path = os.path.join(TMP, f"vv_{key}.jpg")
        with open(path, "wb") as f:
            f.write(data)
        return path

    async def _owner(self, method: str, path: str, body: str = "", **params) -> str:
        headers = {"X-VV-Token": self.token}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as s:
            async with s.request(method, f"{self.api}{path}", params=params, data=body.encode(), headers=headers) as r:
                return await r.text() if r.status == 200 else f"接口返回 {r.status}"

    def _who(self, event: AstrMessageEvent) -> str:
        return f"{event.get_group_id() or 'dm'}|{event.get_sender_id()}"

    def _is_owner(self, event: AstrMessageEvent) -> bool:
        return bool(self.token) and event.get_sender_id() in self.owners

    def _cooling(self, event: AstrMessageEvent) -> bool:
        gid = event.get_group_id() or event.get_sender_id()
        now = time.time()
        if now - self._last.get(gid, 0) < COOLDOWN_S:
            return True
        self._last[gid] = now
        return False

    # ---- commands ------------------------------------------------------------------------
    @filter.command("help")
    async def help(self, event: AstrMessageEvent):
        """/help"""
        yield event.plain_result(HELP)
        event.stop_event()

    @filter.command("vv")
    async def vv(self, event: AstrMessageEvent):
        """/vv 关键字: a random matching picture."""
        query = rest(event.message_str, "vv")
        if not query:
            yield event.plain_result("请输入查询参数喵")
            return
        hits = await self._json("/api/search", q=query, k=6)
        if not hits:
            yield event.plain_result("not found\n请注意, 关键词中的标点符号会被忽略")
            return
        path = await self._image_path(hits[0]["key"])
        logger.info(f"vv_search /vv {query!r} -> {hits[0]['text']!r} ({hits[0]['source']})")
        yield event.image_result(path) if path else event.plain_result("图片发送失败了喵, 请稍后再试")

    @filter.command("r")
    async def random_pic(self, event: AstrMessageEvent):
        """/r: a random picture."""
        hit = await self._json("/api/random")
        path = await self._image_path(hit["key"]) if hit else None
        yield event.image_result(path) if path else event.plain_result("图库还是空的喵")

    @filter.command("acc")
    async def acc(self, event: AstrMessageEvent):
        """/acc 关键字: list the matches; /acc 数字: pick one."""
        arg = rest(event.message_str, "acc", "d")
        if not arg:
            yield event.plain_result("请输入查询参数喵")
            return
        if arg.isdigit():
            result = await self._pick(event, int(arg))
            yield result
            return
        hits = await self._json("/api/search", q=arg, k=ACC_MAX, mode="list")
        if not hits:
            yield event.plain_result("not found\n请注意, 关键词中的标点符号会被忽略")
            return
        if len(hits) == 1:
            path = await self._image_path(hits[0]["key"])
            yield event.image_result(path) if path else event.plain_result("图片发送失败了喵, 请稍后再试")
            return
        self._pending[self._who(event)] = (time.time() + ACC_TTL_S, hits)
        lines = [f"{i + 1} : {h['label']}" for i, h in enumerate(hits)]
        yield event.plain_result("匹配到多张图片, 请发送数字选择\n" + "\n".join(lines))

    async def _pick(self, event: AstrMessageEvent, n: int):
        expires, hits = self._pending.get(self._who(event), (0, []))
        if time.time() > expires or not hits:
            return event.plain_result("没有找到相关缓存喵, 请先 /acc 关键字 查询")
        if not 1 <= n <= len(hits):
            return event.plain_result(f"请输入 1 到 {len(hits)} 之间的数字喵")
        path = await self._image_path(hits[n - 1]["key"])
        return event.image_result(path) if path else event.plain_result("图片发送失败了喵, 请稍后再试")

    # ---- the owner's maintenance commands -----------------------------------------------
    @filter.command("auth")
    async def auth(self, event: AstrMessageEvent):
        """/auth <cookies>: save the cookies used for the weekly download."""
        if not self._is_owner(event):
            return
        text = rest(event.message_str, "auth")
        if not text:
            yield event.plain_result("用法: /auth 后面跟浏览器里复制的 YouTube Cookie 字符串或 cookies.txt 内容; 太长就分几条, 后面的用 /authadd 追加")
            return
        out = await self._owner("POST", "/api/owner/auth", text)
        yield event.plain_result(out + ("\n(下次建议私聊发送, 群里的人能看到)" if event.get_group_id() else ""))

    @filter.command("authadd")
    async def authadd(self, event: AstrMessageEvent):
        """/authadd <more cookies>: append to what /auth saved."""
        if not self._is_owner(event):
            return
        text = rest(event.message_str, "authadd")
        if text:
            yield event.plain_result(await self._owner("POST", "/api/owner/auth", text, append="1"))

    @filter.command("go")
    async def go(self, event: AstrMessageEvent):
        """/go: start the update with the saved cookies."""
        if self._is_owner(event):
            yield event.plain_result(await self._owner("POST", "/api/owner/go"))

    @filter.command("status")
    async def status(self, event: AstrMessageEvent):
        """/status"""
        if self._is_owner(event):
            yield event.plain_result(await self._owner("GET", "/api/owner/status"))

    # ---- everything else said in a group ------------------------------------------------
    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def on_group_message(self, event: AstrMessageEvent):
        """Bare numbers after /acc, and picture requests nobody addressed to the bot."""
        text = (event.message_str or "").strip()
        if not text or text.startswith(("/", "／")) or event.get_sender_id() == event.get_self_id():
            return
        if text.isdigit() and len(text) <= 3 and self._who(event) in self._pending:
            yield await self._pick(event, int(text))
            return
        query = extract_query(text)
        if query is None or self._cooling(event):
            return
        hits = await self._json("/api/search", q=query, k=6)
        if not hits:
            return
        path = await self._image_path(hits[0]["key"])
        if path:
            logger.info(f"vv_search proactive {query!r} -> {hits[0]['text']!r} ({hits[0]['source']}, {hits[0]['score']:.2f})")
            yield event.image_result(path)
