"""Index many episodes in a row without hammering YouTube.

Two stages run side by side: a downloader (one video at a time, rate limited, with pauses) and a
worker that extracts, deletes the video and pushes the result. A bounded queue between them keeps
at most a few videos on disk. Restartable at any point: finished episodes are recognised by their
index file, a half-downloaded video simply resumes.
"""

from __future__ import annotations

import json
import os
import queue
import random
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from . import extract as ex
from . import fetch
from .faces import FaceMatcher
from .subtitle import Reader

MIN_MINUTES, MAX_MINUTES = 15, 70
MAX_CONSECUTIVE_FAILURES = 3
QUEUE_DEPTH = 2


@dataclass
class Push:
    """Where finished episodes go: user@host:/dir (contains entries/ and frames/)."""

    target: str
    key: Path

    def send(self, out_dir: Path, ep: int) -> None:
        host, _, remote = self.target.partition(":")
        name = f"ep{ep:04d}"
        ssh = ["ssh", "-i", str(self.key), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes"]
        scp = ["scp", "-q", "-i", str(self.key), "-o", "IdentitiesOnly=yes", "-o", "BatchMode=yes"]
        pack, idx = out_dir / "frames" / f"{name}.pack", out_dir / "entries" / f"{name}.jsonl"
        # Pack first, index last: the bot only lists episodes that have an index file.
        for src, sub in ((pack, "frames"), (idx, "entries")):
            part = f"{remote}/{sub}/{src.name}.part"
            subprocess.run([*scp, str(src), f"{host}:{part}"], check=True)
            subprocess.run(
                [*ssh, host, f"mv -f '{part}' '{remote}/{sub}/{src.name}' && sync"], check=True
            )


def _keep_awake() -> None:
    if os.name == "nt":
        import ctypes

        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)  # type: ignore[attr-defined]


def _log(msg: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, file=sys.stderr, flush=True)


class _Run:
    """Shared state of one backfill run."""

    def __init__(self, work_dir: Path):
        self.state_path = work_dir / "backfill_state.json"
        self.lock = threading.Lock()
        self.state = (
            json.loads(self.state_path.read_text("utf-8")) if self.state_path.exists() else {}
        )
        self.state.setdefault("failed", {})
        today = date.today().isoformat()
        if self.state.get("day") != today:
            self.state["day"], self.state["downloads_today"] = today, 0
        self.failures = 0
        self.stop_code = 0  # 0 keep going, otherwise the exit code to finish with
        self.stop_event = threading.Event()

    def save(self) -> None:
        with self.lock:
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=1), "utf-8")
            os.replace(tmp, self.state_path)

    def stop(self, code: int, why: str) -> None:
        with self.lock:
            if self.stop_code == 0:
                self.stop_code = code
                self.state["stopped"] = why
        self.stop_event.set()
        _log(f"STOP: {why}")
        self.save()

    def note_failure(self, ep: int, err: Exception) -> None:
        with self.lock:
            self.failures += 1
            n = self.failures
            self.state["failed"][str(ep)] = str(err)[:300]
        _log(f"ep{ep}: FAILED ({n} in a row): {err}")
        if n >= MAX_CONSECUTIVE_FAILURES:
            self.stop(4, f"{n} failures in a row, last at ep{ep}")
        self.save()

    def note_success(self, ep: int, res: dict) -> None:
        with self.lock:
            self.failures = 0
            self.state["failed"].pop(str(ep), None)
            self.state["last_ok"] = {"ep": ep, "lines": res.get("lines"), "at": time.time()}
        self.save()


def run(
    episodes: list[int],
    mapping: dict[int, str],
    cookies: Path,
    out_dir: Path,
    work_dir: Path,
    matcher: FaceMatcher,
    reader: Reader,
    push: Push | None = None,
    max_per_day: int = 120,
    pause: tuple[int, int] = (30, 75),
) -> int:
    _keep_awake()
    work_dir.mkdir(parents=True, exist_ok=True)
    r = _Run(work_dir)
    jobs: queue.Queue[tuple[int, Path] | None] = queue.Queue(maxsize=QUEUE_DEPTH)

    def worker() -> None:
        while (job := jobs.get()) is not None:
            ep, video = job
            try:
                _log(f"ep{ep}: extracting")
                res = ex.extract_episode(video, ep, out_dir, matcher, reader, log=sys.stderr)
                video.unlink(missing_ok=True)
                if push:
                    push.send(out_dir, ep)
                _log(f"ep{ep}: done {res}")
                r.note_success(ep, res)
            except Exception as err:  # noqa: BLE001 - one bad episode must not end a long run
                r.note_failure(ep, err)

    t = threading.Thread(target=worker, name="extract", daemon=True)
    t.start()

    for ep in episodes:
        if r.stop_event.is_set():
            break
        if (out_dir / "entries" / f"ep{ep:04d}.jsonl").exists():
            continue
        vid = mapping.get(ep)
        if not vid:
            _log(f"ep{ep}: no YouTube video mapped, skipping")
            continue
        if r.state["downloads_today"] >= max_per_day:
            r.stop(0, f"daily limit of {max_per_day} downloads reached")
            break
        try:
            _log(f"ep{ep}: downloading {vid}")
            video = fetch.download(vid, work_dir / "dl", cookies)
            r.state["downloads_today"] += 1
            minutes = fetch.duration_seconds(video) / 60
            if not MIN_MINUTES <= minutes <= MAX_MINUTES:
                video.unlink(missing_ok=True)
                raise RuntimeError(f"unexpected duration {minutes:.1f} min")
        except fetch.BotCheckError as err:
            r.stop(3, f"bot-check at ep{ep}: {err}")
            break
        except Exception as err:  # noqa: BLE001
            r.note_failure(ep, err)
            continue
        jobs.put((ep, video))  # blocks while the worker is two episodes behind
        r.save()
        if r.stop_event.wait(random.uniform(*pause)):
            break

    jobs.put(None)
    t.join()
    if r.stop_code == 0 and not r.state.get("stopped", "").startswith("daily"):
        r.state["stopped"] = "finished"
        r.save()
        _log("all requested episodes are done")
    return r.stop_code
