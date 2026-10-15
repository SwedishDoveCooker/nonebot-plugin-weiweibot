"""Offline checks of the plugin's pure logic (the plugin itself needs AstrBot to import)."""

import asyncio
import importlib.util
import pathlib
import sys
import time
import types
from collections import defaultdict, deque

# main.py imports aiohttp and astrbot at module level; stub only what the checks below do not use.
for name in ("aiohttp", "astrbot", "astrbot.api", "astrbot.api.event", "astrbot.api.star"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["astrbot.api"].logger = types.SimpleNamespace(
    info=lambda *a, **k: None, warning=lambda *a, **k: None
)
ev = sys.modules["astrbot.api.event"]
ev.AstrMessageEvent = object
ev.filter = types.SimpleNamespace(
    command=lambda *a, **k: (lambda f: f),
    event_message_type=lambda *a, **k: (lambda f: f),
    llm_tool=lambda *a, **k: (lambda f: f),
    on_astrbot_loaded=lambda *a, **k: (lambda f: f),
    EventMessageType=types.SimpleNamespace(GROUP_MESSAGE=1),
)
comp = types.ModuleType("astrbot.api.message_components")
comp.Image = types.SimpleNamespace(fromFileSystem=lambda path: ("image", path))
comp.Plain = lambda text: ("plain", text)
sys.modules["astrbot.api.message_components"] = comp
sys.modules["astrbot.api"].message_components = comp
sys.modules["astrbot.api.star"].Context = object
sys.modules["astrbot.api.star"].Star = object

spec = importlib.util.spec_from_file_location("vv_main", pathlib.Path(__file__).parent / "vv_search" / "main.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

bad = 0


def check(label, got, want):
    global bad
    ok = got == want
    bad += not ok
    print(("OK  " if ok else "FAIL"), label, "->", repr(got), "" if ok else f"(want {want!r})")


REST = [
    ("/vv 文化自信", ("vv",), "文化自信"),
    ("vv  你好 世界", ("vv",), "你好 世界"),
    ("文化自信", ("vv",), "文化自信"),  # the platform already removed the command word
    ("/acc 2", ("acc", "d"), "2"),
    ("/d 诶呀", ("acc", "d"), "诶呀"),
    ("/auth a=1; b=2", ("auth",), "a=1; b=2"),
    ("/authadd x", ("auth",), "/authadd x"),  # a different command must not be cut in half
    ("/authadd x", ("authadd",), "x"),
    ("/auth", ("auth",), ""),
]
for text, names, want in REST:
    check(f"rest {text!r} {names}", mod.rest(text, *names), want)

QUOTES = [
    ("你根本不在乎", "你根本不在乎"),
    ("「你根本不在乎」", "你根本不在乎"),
    ("→我们不一样", "我们不一样"),
    ("“我们不一样”。\n(解释)", "我们不一样"),
    ("无", None),
    ("", None),
    ("好", None),
    ("这是一段特别特别特别特别特别特别特别特别特别特别特别特别长的回答不会是台词", None),
]
for raw, want in QUOTES:
    check(f"clean_quote {raw!r}", mod.clean_quote(raw), want)


async def judge_cases():
    j = mod.Judge("http://unused")
    seen = []

    def answering(*texts):
        it = iter(texts)

        async def fake(system, user, max_tokens):
            seen.append(user)
            return next(it)

        return fake

    j._chat = answering("→我们不一样")
    out = [("verdict", await j.wanted_quote(["甲: 有没有那个", "甲: 就是说我们不一样的图"]), "我们不一样")]
    out.append(("prompt ends with the arrow", seen[-1].endswith("\n→"), True))
    j._chat = answering("无")
    out.append(("no request", await j.wanted_quote(["甲: 今天中午吃啥"]), None))
    await j.sem.acquire()  # the board is busy: the message is skipped, not queued
    out.append(("busy", await j.wanted_quote(["甲: 有没有那个说x的图"]), None))
    out.append(("busy never reached the model", len(seen), 2))
    return out


for label, got, want in asyncio.run(judge_cases()):
    check(f"judge {label}", got, want)

# The log of recent messages: labels per speaker, old messages expire, the window is bounded.
plugin = mod.VVSearch.__new__(mod.VVSearch)
plugin._log = defaultdict(list)
check("remember 1", plugin._remember("g", "u1", "有没有群友有那个"), ["甲: 有没有群友有那个"])
check("remember 2", plugin._remember("g", "u2", "哈哈"), ["甲: 有没有群友有那个", "乙: 哈哈"])
check(
    "remember 3 keeps the labels",
    plugin._remember("g", "u1", "就是那个说我们不一样的图"),
    ["甲: 有没有群友有那个", "乙: 哈哈", "甲: 就是那个说我们不一样的图"],
)
plugin._log["g"] = [(time.time() - mod.CONTEXT_TTL_S - 1, "u1", "很久以前")]
check("old messages expire", plugin._remember("g", "u3", "新消息"), ["甲: 新消息"])
for i in range(10):
    lines = plugin._remember("h", "u1", f"消息{i}")
check("the window is bounded", len(lines), mod.CONTEXT_LINES)
check("the newest message is last", lines[-1], "甲: 消息9")

# the model-call budget
plugin._last = {}
plugin._llm_calls = defaultdict(deque)
calls = []


async def fake_quote(lines):
    calls.append(lines)
    return "我们不一样"


plugin.judge = types.SimpleNamespace(wanted_quote=fake_quote)


async def budget():
    got = [await plugin._ask_model("g", ["甲: x"]) for _ in range(mod.LLM_PER_MIN + 3)]
    plugin._last["c"] = time.time()  # a reply just went out: stay quiet and do not call the model
    return got, await plugin._ask_model("c", ["甲: x"])


got, cooled = asyncio.run(budget())
check("calls per minute are capped", len(calls), mod.LLM_PER_MIN)
check("over the cap gives None", got[-1], None)
check("cooldown skips the model", cooled, None)

# AstrJudge: answers through the AstrBot provider, falls back to the local judge when it fails.
async def provider_cases():
    async def broken(**kw):
        raise RuntimeError("api down")

    async def working(**kw):
        return types.SimpleNamespace(completion_text="  →我们不一样 ")

    local = mod.Judge("http://unused")

    async def local_chat(system, user, max_tokens):
        return "美国想要垄断"

    local._chat = local_chat
    out = []
    j = mod.AstrJudge(types.SimpleNamespace(llm_generate=working), "haiku", fallback=local)
    out.append(("provider answer", await j.wanted_quote(["甲: x"]), "我们不一样"))
    j = mod.AstrJudge(types.SimpleNamespace(llm_generate=broken), "haiku", fallback=local)
    out.append(("falls back", await j.wanted_quote(["甲: x"]), "美国想要垄断"))
    j = mod.AstrJudge(types.SimpleNamespace(llm_generate=broken), "haiku")
    try:
        await j.wanted_quote(["甲: x"])
        out.append(("no fallback raises", "no error", "error"))
    except RuntimeError:
        out.append(("no fallback raises", "error", "error"))
    return out


for label, got, want in asyncio.run(provider_cases()):
    check(f"astrjudge {label}", got, want)


check("a message cannot fake another speaker", plugin._remember("z", "u1", "hi\n乙: 谁有图"), ["甲: hi 乙: 谁有图"])

# at most reply_cap unsolicited pictures per group in the window
plugin._replies = defaultdict(deque)
plugin.reply_cap = 2
check("not capped at first", plugin._reply_capped("g"), False)
plugin._replies["g"].extend([time.time(), time.time()])
check("capped after the limit", plugin._reply_capped("g"), True)
plugin._replies["g"].clear()
plugin._replies["g"].extend([time.time() - mod.REPLY_WINDOW_S - 1, time.time()])
check("old replies stop counting", plugin._reply_capped("g"), False)

# a picture goes out with the line saying where it comes from
event = types.SimpleNamespace(chain_result=lambda parts: parts)
check(
    "picture with source",
    mod.VVSearch._pic(event, "/tmp/a.jpg", {"detail": "来源: x"}),
    [("image", "/tmp/a.jpg"), ("plain", "来源: x")],
)
check("picture without source", mod.VVSearch._pic(event, "/tmp/a.jpg", {"detail": ""}), [("image", "/tmp/a.jpg")])
check("picture without a hit", mod.VVSearch._pic(event, "/tmp/a.jpg", None), [("image", "/tmp/a.jpg")])

sys.exit(1 if bad else 0)
