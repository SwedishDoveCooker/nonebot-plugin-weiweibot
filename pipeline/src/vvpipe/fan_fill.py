"""Fill gaps in the episode list from other uploads, but only what can be proven to be the episode.

Some episodes of the show are not on the official YouTube channel. Fans upload them to Bilibili.
Such a video is only taken after its subtitles were read and checked against VV's index (same
episode number: most lines must be the same lines). For episodes VV does not cover the length
of the video must match the official one instead. A wrong or cut-down upload is thrown away.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

from . import bili_fetch as bf
from . import extract as ex
from . import sources

MIN_OVERLAP = 0.6  # share of VV's distinct lines that must be in the upload
LENGTH_TOLERANCE = 0.08


def norm(text: str) -> str:
    return "".join(c for c in text.lower() if c.isalnum())


def vv_lines(entries_json: Path, episode: int) -> set[str]:
    """Distinct normalised lines VV has for an episode (empty when VV does not cover it)."""
    out: set[str] = set()
    for e in json.loads(entries_json.read_text("utf-8")):
        m = re.match(r"\[P\d+\](\d+)", e.get("filename", ""))
        if m and int(m.group(1)) == episode and len(norm(e["text"])) >= 6:
            out.add(norm(e["text"]))
    return out


def overlap(index_dir: Path, ep: int, reference: set[str]) -> float:
    """Share of the reference lines that also appear in the extracted episode."""
    path = index_dir / "entries" / f"ep{ep:04d}.jsonl"
    mine = {norm(json.loads(line)["text"]) for line in path.read_text("utf-8").splitlines() if line}
    return len(mine & reference) / len(reference) if reference else 0.0


def length_matches(video_s: float, official_s: float) -> bool:
    return abs(video_s - official_s) <= LENGTH_TOLERANCE * official_s


def accept(
    index_dir: Path, ep: int, reference: set[str], video_s: float, official_s: float | None
) -> tuple[bool, str]:
    """Is the extracted episode really episode ``ep``? Returns (yes, reason)."""
    if reference:
        share = overlap(index_dir, ep, reference)
        return share >= MIN_OVERLAP, f"{share:.0%} of VV's lines found"
    if official_s:
        ok = length_matches(video_s, official_s)
        return ok, f"length {video_s / 60:.1f} min vs official {official_s / 60:.1f} min"
    return False, "nothing to check it against"


def adopt(staged: Path, final: Path, ep: int) -> None:
    """Move a checked episode from the staging index into the real one (index file last)."""
    name = f"ep{ep:04d}"
    for sub, suffix in (("frames", ".pack"), ("sources", ".json"), ("entries", ".jsonl")):
        src = staged / sub / f"{name}{suffix}"
        if src.exists():
            (final / sub).mkdir(parents=True, exist_ok=True)
            tmp = final / sub / f"{name}{suffix}.tmp"
            shutil.copyfile(src, tmp)
            tmp.replace(final / sub / f"{name}{suffix}")


def run(
    candidates: dict[int, list[dict]],
    session: bf.Session,
    out_dir: Path,
    work_dir: Path,
    vv_json: Path,
    official_s: dict[int, float],
    matcher,
    reader,
    titles: dict[int, str],
    push=None,
    log=sys.stderr,
) -> dict:
    state_path = work_dir / "fan_state.json"
    state = json.loads(state_path.read_text("utf-8")) if state_path.exists() else {}
    counts: dict[str, int] = defaultdict(int)
    for ep in sorted(candidates):
        if (out_dir / "entries" / f"ep{ep:04d}.jsonl").exists() or state.get(str(ep), {}).get("ok"):
            continue
        reference = vv_lines(vv_json, ep)
        for cand in candidates[ep]:
            if cand["bvid"] in state.get(str(ep), {}).get("tried", []):
                continue
            rec = state.setdefault(str(ep), {"tried": []})
            rec["tried"].append(cand["bvid"])
            staged = work_dir / "stage"
            try:
                video = bf.download(session, cand["bvid"], work_dir / "dl")
                length = ex_duration(video)
                ex.extract_episode(video, ep, staged, matcher, reader)
                video.unlink(missing_ok=True)
            except bf.NoHighQuality as err:
                print(f"ep{ep} {cand['bvid']}: {err}", file=log)
                counts["lowres"] += 1
                continue
            except Exception as err:  # noqa: BLE001 - one bad upload must not stop the run
                print(f"ep{ep} {cand['bvid']}: failed: {err}", file=log)
                counts["failed"] += 1
                continue
            ok, why = accept(staged, ep, reference, length, official_s.get(ep))
            verdict = "ACCEPTED" if ok else "rejected"
            print(f"ep{ep} {cand['bvid']} {cand['title'][:24]}: {verdict} ({why})", file=log)
            if ok:
                sources.write(staged, ep, "ztjzg", title=titles.get(ep, ""), id=cand["bvid"])
                adopt(staged, out_dir, ep)
                if push:
                    push.send(out_dir, ep)
                rec.update(ok=True, bvid=cand["bvid"], why=why)
                counts["accepted"] += 1
            else:
                counts["rejected"] += 1
            for sub in ("entries", "frames", "sources"):  # the staging area is reused
                for f in (staged / sub).glob(f"ep{ep:04d}.*"):
                    f.unlink(missing_ok=True)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), "utf-8")
            if ok:
                break
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), "utf-8")
    return dict(counts)


def ex_duration(video: Path) -> float:
    from .fetch import duration_seconds

    return duration_seconds(video)
