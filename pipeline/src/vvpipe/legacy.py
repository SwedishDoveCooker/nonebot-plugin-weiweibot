"""Bring the old nonebot-plugin-weiweibot picture set into the index.

That plugin ships assets.tar.gz: one JPEG per picture, named "<line of text>.jpg" (a "-2" style
suffix tells apart pictures with the same text). They carry no episode or time, so the whole set
becomes one source ("legacy") with unknown face similarity.
"""

from __future__ import annotations

import json
import os
import re
import tarfile
from pathlib import Path

from . import sources

_SUFFIX = re.compile(r"-\d+$")


def caption(filename: str) -> str:
    stem = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return _SUFFIX.sub("", stem).strip()


def import_tar(
    tar_path: Path, index_dir: Path, ep: int = sources.LEGACY_EP, force: bool = False
) -> dict:
    name = f"ep{ep:04d}"
    entries, frames = index_dir / "entries", index_dir / "frames"
    entries.mkdir(parents=True, exist_ok=True)
    frames.mkdir(parents=True, exist_ok=True)
    idx_path, pack_path = entries / f"{name}.jsonl", frames / f"{name}.pack"
    if idx_path.exists() and not force:
        return {"ep": ep, "skipped": True}

    pack_tmp, idx_tmp = pack_path.with_suffix(".pack.tmp"), idx_path.with_suffix(".jsonl.tmp")
    rows = skipped = 0
    with (
        tarfile.open(tar_path, "r:gz", encoding="utf-8", errors="replace") as tar,
        open(pack_tmp, "wb") as pack,
        open(idx_tmp, "w", encoding="utf-8") as idx,
    ):
        for member in sorted((m for m in tar if m.isfile()), key=lambda m: m.name):
            text = caption(member.name)
            if not member.name.lower().endswith(".jpg") or not text or "�" in text:
                skipped += 1
                continue
            data = tar.extractfile(member).read()  # type: ignore[union-attr]
            off = pack.tell()
            pack.write(data)
            row = {"ep": ep, "t": 0, "text": text, "sim": -1, "off": off, "len": len(data), "h": 0}
            idx.write(json.dumps(row, ensure_ascii=False) + "\n")
            rows += 1
        pack.flush()
        os.fsync(pack.fileno())
        idx.flush()
        os.fsync(idx.fileno())
    os.replace(pack_tmp, pack_path)  # pack first, index last: the bot lists episodes by index
    os.replace(idx_tmp, idx_path)
    sources.write(index_dir, ep, "legacy", title="旧图库 (nonebot-plugin-weiweibot)")
    return {
        "ep": ep,
        "lines": rows,
        "skipped_files": skipped,
        "pack_mb": round(pack_path.stat().st_size / 1e6, 1),
    }
