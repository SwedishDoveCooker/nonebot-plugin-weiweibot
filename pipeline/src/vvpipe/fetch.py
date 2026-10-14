"""Gentle YouTube downloads: one video at a time, rate limited, resumable."""

from __future__ import annotations

import subprocess
from pathlib import Path

import yt_dlp

# 1080p H.264 + AAC when available (about 350 MB for a 35-minute episode).
FORMAT = "bv*[height<=1080][vcodec^=avc1]+ba[ext=m4a]/bv*[height<=1080]+ba/b[height<=1080]"
RATE_LIMIT = 4 * 1024 * 1024  # bytes per second

_BOT_MARKERS = ("not a bot", "Sign in to confirm", "page needs to be reloaded", "HTTP Error 429")


class BotCheckError(RuntimeError):
    """YouTube asked for verification or is throttling: stop everything and tell the owner."""


def download(video_id: str, dest_dir: Path, cookies: Path, rate: int = RATE_LIMIT) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    opts = {
        "format": FORMAT,
        "cookiefile": str(cookies),
        "ratelimit": rate,
        "retries": 3,
        "fragment_retries": 3,
        "concurrent_fragment_downloads": 1,
        "sleep_interval_requests": 1.5,
        "outtmpl": str(dest_dir / f"{video_id}.%(ext)s"),
        "merge_output_format": "mkv",
        "noprogress": True,
        "quiet": True,
        "no_warnings": True,
        "continuedl": True,
        "overwrites": False,
    }
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
            return p
    raise FileNotFoundError(f"download of {video_id} produced no video file")


def duration_seconds(video: Path) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0"]
    out = subprocess.run([*cmd, str(video)], capture_output=True, text=True, check=False)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0
