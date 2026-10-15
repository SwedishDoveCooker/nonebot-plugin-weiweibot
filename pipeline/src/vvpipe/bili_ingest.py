"""Index every video of a Bilibili account, and keep up with the new ones.

One video becomes one source with its own id (see ``sources.next_id``). The state file remembers
what was done, so a stopped run resumes where it was; a video that only comes in below 1080p is
remembered as such and retried later instead of being indexed.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import bili_fetch as bf
from . import extract as ex
from . import sources

LOW_HEIGHT = 700  # the floor for the videos the owner approved at 720p
MAX_PARTS = 6
MAX_SECONDS = 3 * 3600
RETRIES_PER_VIDEO = 3


def _log(msg: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, file=sys.stderr, flush=True)


@dataclass
class State:
    path: Path
    data: dict = field(default_factory=lambda: {"videos": {}})

    @classmethod
    def load(cls, path: Path) -> State:
        try:
            return cls(path, json.loads(path.read_text("utf-8")))
        except (OSError, ValueError):
            return cls(path)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), "utf-8")
        os.replace(tmp, self.path)

    def get(self, bvid: str) -> dict:
        return self.data["videos"].get(bvid, {})

    def set(self, bvid: str, **fields) -> None:
        self.data["videos"].setdefault(bvid, {}).update(fields)
        self.save()

    def todo(self, videos: list[bf.Video]) -> list[bf.Video]:
        def open_(v: bf.Video) -> bool:
            rec = self.get(v.bvid)
            return rec.get("status") != "done" and rec.get("tries", 0) < RETRIES_PER_VIDEO

        return [v for v in videos if open_(v)]


def process_video(
    session: bf.Session,
    video: bf.Video,
    state: State,
    out_dir: Path,
    work_dir: Path,
    matcher,
    reader,
    log=_log,
    min_height: int = bf.MIN_HEIGHT,
) -> list[int]:
    """Download, index and record one video (all its parts); returns the ids it got."""
    prev = state.get(video.bvid)
    ids: list[int] = list(prev.get("ids", []))
    parts = session.parts(video.bvid)[:MAX_PARTS]
    for i, part in enumerate(parts):
        if i < len(ids):
            continue  # an earlier run already indexed this part
        title = (
            video.title
            if len(parts) == 1
            else f"{video.title} P{i + 1} {part.get('part', '')}".strip()
        )
        file = bf.download(
            session, video.bvid, work_dir / "dl", part_index=i, min_height=min_height
        )
        ep = sources.next_id(out_dir)
        log(f"{video.bvid} part {i + 1}/{len(parts)}: extracting as ep{ep}")
        res = ex.extract_episode(file, ep, out_dir, matcher, reader, min_height=min_height)
        sources.write(out_dir, ep, "bili", title=title, id=video.bvid, pub=video.pub)
        file.unlink(missing_ok=True)
        ids.append(ep)
        state.set(video.bvid, ids=ids)
        log(f"{video.bvid} part {i + 1}: {res.get('lines')} lines")
    return ids


def run(
    session: bf.Session,
    videos: list[bf.Video],
    state: State,
    out_dir: Path,
    work_dir: Path,
    matcher,
    reader,
    on_done=None,
    stop_after: int | None = None,
    log=_log,
    allow_low: frozenset[str] | set[str] = frozenset(),
) -> dict:
    """Process every video that is not done yet. Returns counters."""
    counts = {"done": 0, "lowres": 0, "failed": 0, "skipped": 0}
    for video in state.todo(videos):
        if stop_after is not None and counts["done"] >= stop_after:
            break
        if video.length_s > MAX_SECONDS:
            state.set(video.bvid, status="skipped", why=f"{video.length_s // 60} min is too long")
            counts["skipped"] += 1
            continue
        try:
            # a few videos exist only in 720p; the owner has approved those one by one
            floor = LOW_HEIGHT if video.bvid in allow_low else bf.MIN_HEIGHT
            ids = process_video(
                session, video, state, out_dir, work_dir, matcher, reader, log, min_height=floor
            )
        except bf.NoHighQuality as err:
            state.set(
                video.bvid,
                status="lowres",
                why=str(err),
                tries=state.get(video.bvid).get("tries", 0) + 1,
            )
            counts["lowres"] += 1
            log(f"{video.bvid}: {err}")
            continue
        except bf.Blocked as err:
            log(f"{video.bvid}: Bilibili asks to slow down ({err}); waiting 5 minutes")
            time.sleep(300)
            continue
        except Exception as err:  # noqa: BLE001 - one bad video must not end a long run
            tries = state.get(video.bvid).get("tries", 0) + 1
            state.set(video.bvid, status="failed", why=str(err)[:300], tries=tries)
            counts["failed"] += 1
            log(f"{video.bvid}: failed ({tries}/{RETRIES_PER_VIDEO}): {err}")
            continue
        state.set(
            video.bvid,
            status="done",
            title=video.title,
            pub=video.pub,
            done_at=dt.datetime.now().isoformat(timespec="seconds"),
        )
        counts["done"] += 1
        if on_done:
            on_done(video, ids)
    return counts
