"""Gentle YouTube downloads: one video at a time, rate limited, resumable."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yt_dlp

# 1080p H.264 + AAC when available (about 350 MB for a 35-minute episode).
MIN_HEIGHT = 1000  # never accept less than 1080p: a soft-blocked session may offer only 360p
FORMAT = (
    "bv*[height<=1080][height>=1000][vcodec^=avc1]+ba[ext=m4a]"
    "/bv*[height<=1080][height>=1000]+ba"
    "/b[height<=1080][height>=1000]"  # a combined stream, e.g. the HLS one of web_safari
)
RATE_LIMIT: int | None = None  # bytes per second; None means unlimited

_BOT_MARKERS = (
    "not a bot",
    "Sign in to confirm",
    "page needs to be reloaded",
    "HTTP Error 429",
    "Requested format is not available",  # only low-quality formats were offered
)


class BotCheckError(RuntimeError):
    """YouTube asked for verification or is throttling: stop everything and tell the owner."""


def download(
    video_id: str,
    dest_dir: Path,
    cookies: Path | None = None,
    rate: int | None = RATE_LIMIT,
    browser_profile: Path | None = None,
    player_client: str | None = None,
    proxy: str | None = None,
) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    opts: dict = {
        "format": FORMAT,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 4,  # HLS has hundreds of small fragments
        "outtmpl": str(dest_dir / f"{video_id}.%(ext)s"),
        "merge_output_format": "mkv",
        "noprogress": True,
        "quiet": True,
        "no_warnings": True,
        "continuedl": True,
        "overwrites": False,
    }
    if browser_profile is not None:  # the live login of a Firefox that stays open
        opts["cookiesfrombrowser"] = ("firefox", str(browser_profile), None, None)
    elif cookies is not None:
        opts["cookiefile"] = str(cookies)
    if deno := os.environ.get("VVPIPE_DENO"):  # without a JS runtime YouTube only lists thumbnails
        opts["js_runtimes"] = {"deno": {"path": deno}}
    if rate:
        opts["ratelimit"] = rate
    if proxy:
        opts["proxy"] = proxy
    if player_client:  # e.g. web_safari still offers 1080p while the default client is downgraded
        opts["extractor_args"] = {"youtube": {"player_client": [player_client]}}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
    except yt_dlp.utils.DownloadError as err:
        text = str(err)
        if any(m in text for m in _BOT_MARKERS):
            raise BotCheckError(text.splitlines()[0][:200]) from err
        raise
    for p in sorted(dest_dir.glob(f"{video_id}.*")):
        if p.suffix in (".mkv", ".mp4", ".webm"):
            height = video_height(p)
            if height < MIN_HEIGHT:
                p.unlink(missing_ok=True)
                raise BotCheckError(f"only {height}p was delivered for {video_id}")
            return p
    raise FileNotFoundError(f"download of {video_id} produced no video file")


def video_height(video: Path) -> int:
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=height"]
    out = subprocess.run(
        [*cmd, "-of", "csv=p=0", str(video)], capture_output=True, text=True, check=False
    )
    try:
        return int(out.stdout.strip().split(",")[0])
    except ValueError:
        return 0


def duration_seconds(video: Path) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0"]
    out = subprocess.run([*cmd, str(video)], capture_output=True, text=True, check=False)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0
