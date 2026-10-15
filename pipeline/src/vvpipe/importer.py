"""Index videos that someone already downloaded into a folder.

The episode number comes from the file name ("第351期", "EP351", "351 ...") or, failing that,
from the closest Bilibili episode title. Finished videos are moved to <dir>/done, never deleted.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from collections.abc import Callable
from difflib import SequenceMatcher
from pathlib import Path

from . import extract as ex
from . import fetch
from .backfill import MAX_MINUTES, MIN_MINUTES, Push
from .faces import FaceMatcher
from .subtitle import Reader

VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}
_EP_PATTERNS = (
    re.compile(r"第\s*(\d{1,3})\s*[期集]"),
    re.compile(r"(?<![A-Za-z0-9])EP\s*[-_ ]?(\d{1,3})(?!\d)", re.IGNORECASE),
    re.compile(r"^\s*[\[(【]?(\d{3})[\])】]?(?!\d)"),
)


def _norm(s: str) -> str:
    return "".join(ch for ch in s if ch.isalnum())


def episode_from_name(name: str, titles: dict[int, str] | None = None) -> int | None:
    stem = Path(name).stem
    for pat in _EP_PATTERNS:
        m = pat.search(stem)
        if m:
            return int(m.group(1))
    if titles:
        topic = _norm(stem)
        best = max(((SequenceMatcher(None, topic, _norm(t)).ratio(), n) for n, t in titles.items()),
                   default=(0.0, 0))  # fmt: skip
        if best[0] >= 0.5:
            return best[1]
    return None


def load_titles(path: Path | None) -> dict[int, str]:
    if not path or not path.exists():
        return {}
    rows = json.loads(path.read_text("utf-8"))
    return {int(r["n"]): re.sub(r"^《这就是中国》第\d+集\s*", "", r["share"] or "") for r in rows}


def _settled(p: Path, wait: float = 3.0) -> bool:
    """A file that is still growing is still being downloaded."""
    a = p.stat().st_size
    time.sleep(wait)
    return a == p.stat().st_size and a > 0


def import_once(
    folder: Path,
    out_dir: Path,
    matcher: FaceMatcher,
    reader: Reader,
    titles: dict[int, str],
    push: Push | None = None,
    log=sys.stderr,
    notify: Callable[[str], None] | None = None,
    on_done: Callable[[int], None] | None = None,
) -> int:
    """Process every ready video in the folder; returns how many episodes were indexed.

    notify gets a short human-readable text for the admin group; on_done gets the episode number
    once it is live (or was already live).
    """
    done_dir = folder / "done"
    n_done = 0
    for video in pending_videos(folder):
        if not _settled(video):
            print(f"{video.name}: still being written, later", file=log)
            continue
        ep = episode_from_name(video.name, titles)
        if ep is None:
            print(
                f"{video.name}: cannot tell which episode this is; put 第N期 in the name", file=log
            )
            continue
        minutes = fetch.duration_seconds(video) / 60
        # VVPIPE_MIN_MINUTES lets a short clip through for an end-to-end smoke test.
        if not float(os.environ.get("VVPIPE_MIN_MINUTES", MIN_MINUTES)) <= minutes <= MAX_MINUTES:
            print(f"{video.name}: unexpected duration {minutes:.1f} min, skipped", file=log)
            continue
        if (out_dir / "entries" / f"ep{ep:04d}.jsonl").exists():
            print(f"{video.name}: episode {ep} is already indexed, moving to done", file=log)
        else:
            print(f"{video.name}: episode {ep}, extracting", file=log)
            try:
                res = ex.extract_episode(video, ep, out_dir, matcher, reader, log=log)
            except ex.LowResolutionError as err:
                print(
                    f"{video.name}: {err}; left in the folder, replace it with a 1080p file",
                    file=log,
                )
                if notify:
                    notify(f"第 {ep} 集的视频不是 1080p, 已拒绝: {video.name}")
                video.rename(video.with_suffix(video.suffix + ".lowres"))
                continue
            print(f"ep{ep}: done {res}", file=log)
            if push:
                push.send(out_dir, ep)
            if notify:
                notify(
                    f"第 {ep} 集已识别并上线: {res['lines']} 条字幕, "
                    f"用时 {res['seconds'] / 60:.0f} 分钟, 图库会在 10 分钟内热重载"
                )
            n_done += 1
        done_dir.mkdir(exist_ok=True)
        shutil.move(str(video), str(done_dir / video.name))
        if on_done:
            on_done(ep)
    return n_done


def pending_videos(folder: Path) -> list[Path]:
    """Video files waiting in the folder (not the ones set aside as low resolution)."""
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in VIDEO_SUFFIXES)
