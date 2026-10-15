"""Find this week's episode on YouTube and download it into the inbox.

Only used when the machine has both a cookies file and a proxy that reaches YouTube. It has not
been exercised against YouTube from the bot's box yet; without that configuration the daemon
just asks for the video to be dropped into the inbox.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from difflib import SequenceMatcher
from pathlib import Path

import yt_dlp

from . import fetch
from .daemon import Config

CHANNEL = "UCahKjkez9olNwcpc5pZwzvg"  # SMG Shanghai TV Official Channel
_TITLE_NUM = re.compile(r"这就是中国\s*(?:第\s*(\d+)\s*期|EP\s*(\d+))")
_PREFIX = re.compile(r"^《这就是中国》第\d+集\s*")


def _norm(s: str) -> str:
    return "".join(ch for ch in s if ch.isalnum())


def _topic(youtube_title: str) -> str:
    t = youtube_title.split("｜")[0]
    return _norm(re.sub(r"^.*?(第\s*\d+\s*期|EP\s*\d+)\s*[:：]?", "", t))


def pick(entries: list[dict], ep: int, title: str) -> str | None:
    """Pick the video whose topic matches the Bilibili title (YouTube numbers can be off by one)."""
    want = _norm(_PREFIX.sub("", title))
    best: tuple[float, str] | None = None
    for e in entries:
        m = _TITLE_NUM.search(e.get("title") or "")
        if not m:
            continue
        n = int(m.group(1) or m.group(2))
        if abs(n - ep) > 2:
            continue
        score = 0.0
        if want:
            sm = SequenceMatcher(None, _topic(e["title"]), want)
            score = sm.ratio()
            if sm.find_longest_match().size >= 4:
                score += (
                    0.2  # both titles share a phrase: the wording differs, the topic is the same
                )
        if n == ep:
            score += 0.15  # the number matching is a mild hint, the topic is the evidence
        if best is None or score > best[0]:
            best = (score, e["id"])
    return best[1] if best and best[0] >= 0.5 else None


def find_video(ep: int, title: str, cookies: Path, proxy: str) -> str | None:
    url = f"https://www.youtube.com/channel/{CHANNEL}/search?query=这就是中国 第{ep}期"
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "cookiefile": str(cookies),
        "proxy": proxy,
        "playlist_items": "1-20",
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return pick(list(info.get("entries") or []), ep, title)


def make_fetcher(cfg: Config) -> Callable[[dict], None] | None:
    if not cfg.cookies or not cfg.proxy or not cfg.cookies.exists():
        return None
    cookies, proxy = cfg.cookies, cfg.proxy

    def fetch_episode(job: dict) -> None:
        ep = int(job["ep"])
        vid = find_video(ep, job.get("title", ""), cookies, proxy)
        if vid is None:
            raise RuntimeError("YouTube 上还没有这一期(通常比 B 站晚约 2 小时)")
        staging = cfg.inbox / ".incoming"
        path = fetch.download(vid, staging, cookies, proxy=proxy, player_client="web_safari")
        # Only a finished, verified file may appear in the inbox.
        os.replace(path, cfg.inbox / f"第{ep}期 {vid}{path.suffix}")

    return fetch_episode
