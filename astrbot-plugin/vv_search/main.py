"""AstrBot front-end for the VV picture bot.

Everything that matters (the picture library, the vectors, the weekly update, the notifications)
lives in the Go services on the same machine. This plugin only speaks QQ through AstrBot and
calls their local HTTP API (127.0.0.1:8770), so either front-end can hold the QQ connection.

Commands: /help /vv /r /acc (then a number) and, for the owner, /auth /authadd /go /status.
Without being addressed, a local model reads the recent chat and answers picture requests,\neven ones spread over several messages.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections import defaultdict, deque

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

SYS_ASK = (
    "你在一个QQ群里旁观。下面是群里最近的聊天记录(旧→新)。"
    "判断最新一条之后,群友是不是在向大家要某句台词或某个梗的表情包/图片,"
    "想要的内容可能分好几条消息才说完。如果是,只输出想找的那句台词原文;否则只输出 无。\n"
    "例:\n甲: 有没有群友有那个\n乙: 哈哈\n甲: 就是那个说我们不一样的图\n→我们不一样\n"
    "例:\n甲: 求一张美国想要垄断的梗图\n→美国想要垄断\n"
    "例:\n甲: 有没有群友有那个说「你根本不在乎」的表情包\n→你根本不在乎\n"
    "例:\n甲: 谁有文化自信的图\n乙: 我找找\n→文化自信\n"
    "例:\n甲: 有没有群友有那个\n→无\n"
    "例:\n甲: 今天中午吃啥\n→无"
)
LLM_MIN_SCORE = 0.7  # a guess from the model needs a clearly matching picture before it speaks
LLM_PER_MIN = 12
LLM_TIMEOUT_S = 60
CONTEXT_LINES = 6  # recent messages shown to the model, so a request can span several messages
CONTEXT_TTL_S = 120
LABELS = "甲乙丙丁戊己庚辛"


def clean_quote(raw: str) -> str | None:
    lines = raw.strip().splitlines()
    q = re.sub(r"^[\s\"“'‘「『《→]+|[\s\"”'’」』》。.!！?？]+$", "", lines[0] if lines else "")
    return q if 2 <= len(q) <= 30 and q != "无" else None


class Judge:
    """Asks a local OpenAI-compatible server (llama.cpp on the Jetson) whether to join in."""

    def __init__(self, url: str, model: str = "local"):
        self.url, self.model = url.rstrip("/"), model
        self.sem = asyncio.Semaphore(1)  # the board has one slot: skip rather than queue up

    async def _chat(self, system: str, user: str, max_tokens: int) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "max_tokens": max_tokens,
            "temperature": 0,
            "cache_prompt": True,
        }
        timeout = aiohttp.ClientTimeout(total=LLM_TIMEOUT_S)
        async with aiohttp.ClientSession(timeout=timeout) as s:
            async with s.post(f"{self.url}/v1/chat/completions", json=body) as r:
                r.raise_for_status()
                return (await r.json())["choices"][0]["message"]["content"].strip()

    async def wanted_quote(self, lines: list[str]) -> str | None:
        """The quote being asked for after the newest line, or None.

        One call only: the system prompt and the older lines stay in the server's prompt cache
        (the chat log only ever grows at the end), and the board has a single slot.
        """
        if self.sem.locked():
            return None
        async with self.sem:
            return clean_quote(await self._chat(SYS_ASK, "\n".join(lines) + "\n→", 20))

class AstrJudge(Judge):
    """The same judge, answered by a chat provider configured in AstrBot (model, key, proxy there)."""

    def __init__(self, context, provider_id: str, fallback: Judge | None = None):
        super().__init__("")
        self.context, self.provider_id, self.fallback = context, provider_id, fallback

    async def _chat(self, system: str, user: str, max_tokens: int) -> str:
        try:
            resp = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=self.provider_id, prompt=user, system_prompt=system
                ),
                LLM_TIMEOUT_S,
            )
            return (resp.completion_text or "").strip()
        except Exception as err:  # noqa: BLE001 - fall back to the local model when the API is down
            if self.fallback is None:
                raise
            logger.warning(f"vv_search: provider {self.provider_id} failed ({err!r}), using the local model")
            return await self.fallback._chat(system, user, max_tokens)

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
        llm = cfg.get("llm") or {}
        local = Judge(llm["url"], llm.get("model", "local")) if llm.get("url") else None
        pid = llm.get("provider_id")
        self.judge = AstrJudge(context, pid, fallback=local) if pid else local
        self._llm_calls: dict[str, deque[float]] = defaultdict(deque)
        self._log: dict[str, list[tuple[float, str, str]]] = defaultdict(list)  # group -> (time, who, text)
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

    def _remember(self, gid: str, sender: str, text: str) -> list[str]:
        """Add a message to the group's recent log and return it as labelled lines."""
        now = time.time()
        log = [m for m in self._log[gid] if now - m[0] < CONTEXT_TTL_S]
        log.append((now, sender, text))
        self._log[gid] = log = log[-CONTEXT_LINES:]
        who: dict[str, str] = {}
        for _, s, _ in log:
            who.setdefault(s, LABELS[len(who) % len(LABELS)])
        return [f"{who[s]}: {t}" for _, s, t in log]

    async def _ask_model(self, gid: str, lines: list[str]) -> str | None:
        """Let the local model decide whether the group is asking for a picture (rate limited)."""
        now = time.time()
        if now - self._last.get(gid, 0) < COOLDOWN_S:
            return None
        calls = self._llm_calls[gid]
        while calls and now - calls[0] > 60:
            calls.popleft()
        if len(calls) >= LLM_PER_MIN:
            return None
        calls.append(now)
        try:
            query = await self.judge.wanted_quote(lines)
        except Exception as err:  # noqa: BLE001 - the model being down must not break the bot
            logger.warning(f"vv_search: local model unavailable: {err!r}")
            return None
        logger.info(f"vv_search model verdict for {lines[-1][:40]!r}: {query!r}")
        return query
    @filter.llm_tool(name="search_meme")
    async def search_meme(self, event: AstrMessageEvent, query: str):
        """Find the 这就是中国 picture whose subtitle best matches a quote and send it to the chat.

        Args:
            query(string): the quote or topic to look for
        """
        hits = await self._json("/api/search", q=query, k=6)
        if not hits:
            return "没有找到匹配的图片"
        path = await self._image_path(hits[0]["key"])
        if not path:
            return "图片发送失败"
        await event.send(event.image_result(path))
        return f"已发送图片: {hits[0]['text']}"

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

    @filter.command("judge")
    async def judge(self, event: AstrMessageEvent):
        """/judge 一句话: show what the model makes of a message (owner only, for tuning)."""
        if not self._is_owner(event) or self.judge is None:
            return
        text = rest(event.message_str, "judge")
        if not text:
            return
        try:
            t0 = time.time()
            query = await self.judge.wanted_quote([f"甲: {text}"])
            yield event.plain_result(f"{query!r} ({time.time() - t0:.1f}s)")
        except Exception as err:  # noqa: BLE001
            yield event.plain_result(f"模型调用失败: {err!r}"[:300])
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
        if self.judge is None or not 2 <= len(text) <= 80:
            return
        gid = event.get_group_id() or event.get_sender_id()
        query = await self._ask_model(gid, self._remember(gid, event.get_sender_id(), text))
        if query is None or self._cooling(event):
            return
        self._log[gid] = []  # this request is being answered, do not answer it again
        hits = await self._json("/api/search", q=query, k=6)
        if not hits:
            return
        if hits[0]["source"] != "literal" and hits[0]["score"] < LLM_MIN_SCORE:
            logger.info(f"vv_search model guess {query!r} dropped, best score {hits[0]['score']:.2f}")
            return
        path = await self._image_path(hits[0]["key"])
        if path:
            logger.info(f"vv_search proactive {query!r} -> {hits[0]['text']!r} ({hits[0]['source']}, {hits[0]['score']:.2f})")
            yield event.image_result(path)