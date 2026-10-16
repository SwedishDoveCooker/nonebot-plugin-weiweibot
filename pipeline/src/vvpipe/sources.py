"""Where the pictures of an index come from.

Every indexed "episode" id has an optional record <index>/sources/epNNNN.json. One small file per
source means machines that add videos independently never overwrite each other's records, and the
files travel with the episode when it is pushed. Ids below 10000 are episodes of the show; larger
ids are other sources (see ``next_id``).

    {"kind": "ztjzg" | "bili" | "legacy", "title": "...", "id": "BV...", "pub": "2025-03-01"}
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

SHOW_MAX_EP = 9999
BILI_FIRST_ID = 10000
LEGACY_EP = 90000
_SHOW_PREFIX = re.compile(r"^《这就是中国》第\d+集\s*")


def path(index_dir: Path, ep: int) -> Path:
    return index_dir / "sources" / f"ep{ep:04d}.json"


def read(index_dir: Path, ep: int) -> dict | None:
    try:
        return json.loads(path(index_dir, ep).read_text("utf-8"))
    except (OSError, ValueError):
        return None


def write(
    index_dir: Path, ep: int, kind: str, title: str = "", id: str = "", pub: str = ""
) -> bool:
    """Record a source atomically; returns False when an identical record is already there."""
    rec = {"kind": kind}
    for key, value in (("title", title), ("id", id), ("pub", pub)):
        if value:
            rec[key] = value
    if read(index_dir, ep) == rec:
        return False
    dest = path(index_dir, ep)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False), "utf-8")
    os.replace(tmp, dest)
    return True


def next_id(index_dir: Path) -> int:
    """The next free id for a video that is not an episode of the show."""
    used = [
        int(m.group(1))
        for p in (index_dir / "entries").glob("ep*.jsonl")
        if (m := re.fullmatch(r"ep(\d+)", p.stem)) and BILI_FIRST_ID <= int(m.group(1)) < LEGACY_EP
    ]
    used += [
        int(m.group(1))
        for p in (index_dir / "sources").glob("ep*.json")
        if (m := re.fullmatch(r"ep(\d+)", p.stem)) and BILI_FIRST_ID <= int(m.group(1)) < LEGACY_EP
    ]
    return max(used, default=BILI_FIRST_ID - 1) + 1


def show_titles(bili_json: Path) -> dict[int, str]:
    """Episode number -> title, from the Bilibili season listing kept next to the index."""
    try:
        rows = json.loads(bili_json.read_text("utf-8-sig"))
    except (OSError, ValueError):
        return {}
    out = {}
    for row in rows:
        title = _SHOW_PREFIX.sub("", (row.get("share") or "").strip())
        if row.get("n") and title:
            out[int(row["n"])] = title
    return out


def sync_show(index_dir: Path, bili_json: Path) -> int:
    """Give every indexed episode of the show a source record with its title."""
    titles = show_titles(bili_json)
    n = 0
    for p in sorted((index_dir / "entries").glob("ep*.jsonl")):
        ep = int(p.stem[2:])
        if ep <= SHOW_MAX_EP and ep in titles:
            n += write(index_dir, ep, "ztjzg", title=titles[ep])
    return n


def relabel(index_dir: Path, old: int, new: int) -> int:
    """Re-file an indexed episode under another number (it turned out to be a different episode).

    Rewrites the ``ep`` of every line, copies pack and vectors to the new name, then removes the
    old files, index first so the bot never lists a half-moved episode. Returns the line count.
    """
    entries, frames, vectors = (index_dir / d for d in ("entries", "frames", "vectors"))
    old_name, new_name = f"ep{old:04d}", f"ep{new:04d}"
    if (entries / f"{new_name}.jsonl").exists():
        raise FileExistsError(f"episode {new} is already in the index")
    rows = [
        json.loads(line)
        for line in (entries / f"{old_name}.jsonl").read_text("utf-8").splitlines()
        if line.strip()
    ]
    for row in rows:
        row["ep"] = new
    for folder, suffix in ((frames, ".pack"), (vectors, ".f16")):
        src = folder / f"{old_name}{suffix}"
        if src.exists():
            tmp = folder / f"{new_name}{suffix}.tmp"
            shutil.copyfile(src, tmp)
            os.replace(tmp, folder / f"{new_name}{suffix}")
    tmp = entries / f"{new_name}.jsonl.tmp"
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8")
    os.replace(tmp, entries / f"{new_name}.jsonl")  # the new episode appears only now
    for p in (
        entries / f"{old_name}.jsonl",
        frames / f"{old_name}.pack",
        vectors / f"{old_name}.f16",
        path(index_dir, old),
    ):
        p.unlink(missing_ok=True)
    return len(rows)
