"""Index many episodes in a row without hammering YouTube.

For each episode: download (rate limited) -> extract -> delete the video -> push the result to
the bot's box -> pause. Restartable at any point: finished episodes are recognised by their
index file, a half-downloaded video simply resumes.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
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
    state_path = work_dir / "backfill_state.json"
    state = json.loads(state_path.read_text("utf-8")) if state_path.exists() else {}
    state.setdefault("failed", {})
    today = date.today().isoformat()
    if state.get("day") != today:
        state["day"], state["downloads_today"] = today, 0
    failures = 0

    def save() -> None:
        tmp = state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), "utf-8")
        os.replace(tmp, state_path)

    for ep in episodes:
        idx = out_dir / "entries" / f"ep{ep:04d}.jsonl"
        if idx.exists():
            continue
        vid = mapping.get(ep)
        if not vid:
            _log(f"ep{ep}: no YouTube video mapped, skipping")
            continue
        if state["downloads_today"] >= max_per_day:
            _log(f"daily limit of {max_per_day} downloads reached, stopping")
            save()
            return 0
        state["current"] = {"ep": ep, "id": vid, "since": time.time()}
        save()
        try:
            _log(f"ep{ep}: downloading {vid}")
            video = fetch.download(vid, work_dir / "dl", cookies)
            state["downloads_today"] += 1
            minutes = fetch.duration_seconds(video) / 60
            if not MIN_MINUTES <= minutes <= MAX_MINUTES:
                raise RuntimeError(f"unexpected duration {minutes:.1f} min")
            _log(f"ep{ep}: extracting ({minutes:.0f} min video)")
            res = ex.extract_episode(video, ep, out_dir, matcher, reader, log=sys.stderr)
            video.unlink(missing_ok=True)
            if push:
                push.send(out_dir, ep)
            state["failed"].pop(str(ep), None)
            state["last_ok"] = {"ep": ep, "lines": res.get("lines"), "at": time.time()}
            _log(f"ep{ep}: done {res}")
            failures = 0
        except fetch.BotCheckError as err:
            state["stopped"] = f"bot-check at ep{ep}: {err}"
            save()
            _log(f"STOP: {state['stopped']}")
            return 3
        except Exception as err:  # noqa: BLE001 - one bad episode must not end a long run
            failures += 1
            state["failed"][str(ep)] = str(err)[:300]
            _log(f"ep{ep}: FAILED ({failures} in a row): {err}")
            if failures >= MAX_CONSECUTIVE_FAILURES:
                state["stopped"] = f"{failures} failures in a row, last at ep{ep}"
                save()
                return 4
        state.pop("current", None)
        save()
        time.sleep(random.uniform(*pause))
    state["stopped"] = "finished"
    save()
    _log("all requested episodes are done")
    return 0
