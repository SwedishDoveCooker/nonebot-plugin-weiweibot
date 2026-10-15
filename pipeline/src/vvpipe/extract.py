"""Turn one episode video into a frame pack plus a line index.

One frame per second is scanned. A frame is a candidate when it carries a burned-in subtitle;
consecutive seconds showing the same line collapse into one entry that keeps the frame where
the target person's face matches best. Output per episode (power-cut safe: the index file is
renamed into place last, so an episode is either complete or absent):

    frames/ep0352.pack      concatenated JPEG bytes
    entries/ep0352.jsonl    {"ep","t","text","sim","off","len"} per line
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

import cv2
import numpy as np

from . import subtitle
from .faces import FaceMatcher
from .fetch import MIN_HEIGHT, video_height

W, H = 1920, 1080
MIN_CONF = 0.6
MAX_GAP_S = 2
SAME_LINE_RATIO = 0.75
JPEG_QUALITY = 85


class LowResolutionError(RuntimeError):
    """The source video is below 1080p; blurry frames would be worse than no frames."""


def norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def same_line(a: str, b: str) -> bool:
    """True when two OCR readings are (probably) the same subtitle line."""
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= SAME_LINE_RATIO


def iter_frames(video: Path, fps: int = 1) -> Iterator[tuple[int, np.ndarray]]:
    cmd = [
        "ffmpeg", "-v", "error", "-nostdin", "-i", str(video),
        "-vf", f"fps={fps},scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-",
    ]  # fmt: skip
    size = W * H * 3
    with subprocess.Popen(cmd, stdout=subprocess.PIPE) as proc:
        assert proc.stdout is not None
        i = 0
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            yield i // fps, np.frombuffer(buf, np.uint8).reshape(H, W, 3)
            i += 1


@dataclass
class Group:
    """Consecutive seconds showing one subtitle line."""

    t_first: int
    t_last: int
    sim: float
    frame: np.ndarray
    votes: Counter = field(default_factory=Counter)

    def add(self, t: int, text: str, sim: float, frame: np.ndarray) -> None:
        self.t_last = t
        self.votes[text] += 1
        if sim > self.sim:
            self.sim, self.frame = sim, frame.copy()

    @property
    def text(self) -> str:
        # Most frequent reading wins; ties go to the longer one (truncated readings lose).
        return max(self.votes.items(), key=lambda kv: (kv[1], len(kv[0])))[0]


def _fsync_rename(tmp: Path, final: Path) -> None:
    with open(tmp, "rb+") as f:
        os.fsync(f.fileno())
    os.replace(tmp, final)


def extract_episode(
    video: Path,
    ep: int,
    out_dir: Path,
    matcher: FaceMatcher,
    reader: subtitle.Reader,
    force: bool = False,
    log=sys.stderr,
    min_height: int = MIN_HEIGHT,
) -> dict:
    frames_dir, entries_dir = out_dir / "frames", out_dir / "entries"
    frames_dir.mkdir(parents=True, exist_ok=True)
    entries_dir.mkdir(parents=True, exist_ok=True)
    name = f"ep{ep:04d}"
    pack_path, idx_path = frames_dir / f"{name}.pack", entries_dir / f"{name}.jsonl"
    if idx_path.exists() and not force:
        return {"ep": ep, "skipped": True}
    height = video_height(video)
    if height < min_height:
        raise LowResolutionError(f"{video.name} is only {height}p; {min_height}p is required")

    pack_tmp, idx_tmp = pack_path.with_suffix(".pack.tmp"), idx_path.with_suffix(".jsonl.tmp")
    started = time.time()
    n_ocr = n_frames = 0
    prev_mask: np.ndarray | None = None
    cur: Group | None = None
    lines: list[dict] = []

    with open(pack_tmp, "wb") as pack:

        def close(g: Group | None) -> None:
            if g is None:
                return
            ok, jpg = cv2.imencode(".jpg", g.frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            if not ok:
                return
            off = pack.tell()
            pack.write(jpg.tobytes())
            lines.append(
                {
                    "ep": ep,
                    "t": g.t_first,
                    "text": g.text,
                    "sim": round(g.sim, 3),
                    "off": off,
                    "len": len(jpg),
                    "h": height,
                }
            )

        for t, frame in iter_frames(video):
            n_frames += 1
            if t and t % 300 == 0:
                print(f"  ep{ep}: {t // 60} min, {len(lines)} lines, {n_ocr} OCR", file=log)
            band = subtitle.crop(frame)
            mask = subtitle.white_mask(band)
            if not subtitle.has_text(mask):
                close(cur)
                cur, prev_mask = None, None
                continue

            if cur is not None and subtitle.same_text(prev_mask, mask):
                text = cur.text
            else:
                text, conf = reader.read(band, mask)
                n_ocr += 1
                text = subtitle.strip_sponsor(text)
                if not text or conf < MIN_CONF:
                    close(cur)
                    cur, prev_mask = None, mask
                    continue
            prev_mask = mask

            sim = matcher.similarity(frame)
            if cur is not None and t - cur.t_last <= MAX_GAP_S and same_line(text, cur.text):
                cur.add(t, text, sim, frame)
            else:
                close(cur)
                cur = Group(t, t, sim, frame.copy())
                cur.add(t, text, sim, frame)
        close(cur)

    with open(idx_tmp, "w", encoding="utf-8") as f:
        for row in lines:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    _fsync_rename(pack_tmp, pack_path)
    _fsync_rename(idx_tmp, idx_path)
    return {
        "ep": ep,
        "lines": len(lines),
        "frames": n_frames,
        "ocr_calls": n_ocr,
        "seconds": round(time.time() - started, 1),
        "pack_mb": round(pack_path.stat().st_size / 1e6, 1),
    }
