"""Offline check of the phrase extraction (the plugin itself needs AstrBot to import)."""

import importlib.util
import pathlib
import sys
import types

# main.py imports aiohttp and astrbot at module level; stub only what extract_query does not use.
for name in ("aiohttp", "astrbot", "astrbot.api", "astrbot.api.event", "astrbot.api.star"):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules["astrbot.api"].logger = types.SimpleNamespace(info=lambda *a, **k: None)
ev = sys.modules["astrbot.api.event"]
ev.AstrMessageEvent = object
ev.filter = types.SimpleNamespace(
    command=lambda *a, **k: (lambda f: f),
    event_message_type=lambda *a, **k: (lambda f: f),
    EventMessageType=types.SimpleNamespace(GROUP_MESSAGE=1),
)
sys.modules["astrbot.api.star"].Context = object
sys.modules["astrbot.api.star"].Star = object

spec = importlib.util.spec_from_file_location("vv_main", pathlib.Path(__file__).parent / "vv_search" / "main.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

CASES = [
    ("有没有群友有那个说「你根本不在乎」的表情包", "你根本不在乎"),  # the exact message from the first trial
    ("好像只有", None),
    ("我根本不在乎", None),
    ("有没有群友有这个表情包", None),  # asks, but says nothing to search for
    ("就是那个说「你根本不在乎」的表情包有吗 有没有", "你根本不在乎"),
    ("有没有那个说'美国想要垄断'的图", "美国想要垄断"),
    ("谁有那个说文化自信的表情包", "文化自信"),
    ("今天天气不错", None),
    ("我觉得这个说法不对", None),
]
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
bad = 0
for text, names, want in REST:
    got = mod.rest(text, *names)
    ok = got == want
    bad += not ok
    print(("OK  " if ok else "FAIL"), "rest", repr(text), names, "->", repr(got), "" if ok else f"(want {want!r})")
for text, want in CASES:
    got = mod.extract_query(text)
    ok = got == want
    bad += not ok
    print(("OK  " if ok else "FAIL"), repr(text), "->", repr(got), "" if ok else f"(want {want!r})")
sys.exit(1 if bad else 0)
