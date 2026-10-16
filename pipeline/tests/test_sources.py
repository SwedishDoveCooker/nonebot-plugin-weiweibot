import io
import json
import tarfile
from pathlib import Path

import pytest

from vvpipe import legacy, sources


def _tar(path: Path, files: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as t:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))


def test_caption_drops_the_numbering_suffix():
    assert legacy.caption("assets/哈密瓜.jpg") == "哈密瓜"
    assert legacy.caption("assets/微笑-3.jpg") == "微笑"
    assert legacy.caption("assets/二-三-4.jpg") == "二-三"


def test_legacy_import_writes_pack_index_and_source(tmp_path):
    tar = tmp_path / "a.tar.gz"
    _tar(
        tar,
        {
            "assets/.gitkeep": b"",
            "assets/你好世界.jpg": b"AAA",
            "assets/你好世界-2.jpg": b"BBBB",
            "assets/乐-3.jpg": b"C",
        },
    )
    out = tmp_path / "idx"
    res = legacy.import_tar(tar, out)
    # only the dotfile is skipped: one-character captions are real pictures
    assert res["lines"] == 3 and res["skipped_files"] == 1
    rows = [
        json.loads(line) for line in (out / "entries/ep90000.jsonl").read_text("utf-8").splitlines()
    ]
    assert sorted(r["text"] for r in rows) == ["乐", "你好世界", "你好世界"]
    pack = (out / "frames/ep90000.pack").read_bytes()
    assert sorted(pack[r["off"] : r["off"] + r["len"]] for r in rows) == [b"AAA", b"BBBB", b"C"]
    assert all(r["sim"] == -1 and r["ep"] == 90000 for r in rows)
    assert sources.read(out, 90000)["kind"] == "legacy"
    assert legacy.import_tar(tar, out) == {"ep": 90000, "skipped": True}  # idempotent
    assert not list(out.rglob("*.tmp"))


def test_source_records_are_atomic_and_idempotent(tmp_path):
    assert sources.write(tmp_path, 352, "ztjzg", title="标题")
    assert not sources.write(tmp_path, 352, "ztjzg", title="标题")
    assert sources.write(tmp_path, 352, "ztjzg", title="新标题")
    assert sources.read(tmp_path, 352) == {"kind": "ztjzg", "title": "新标题"}
    assert sources.read(tmp_path, 1) is None


def test_next_id_skips_what_is_taken(tmp_path):
    assert sources.next_id(tmp_path) == 10000
    (tmp_path / "entries").mkdir()
    (tmp_path / "entries" / "ep10000.jsonl").write_text("{}\n")
    (tmp_path / "entries" / "ep352.jsonl").write_text("{}\n")  # the show does not count
    sources.write(tmp_path, 10003, "bili", title="t", id="BV1")
    (tmp_path / "entries" / "ep90000.jsonl").write_text("{}\n")  # nor does the legacy set
    assert sources.next_id(tmp_path) == 10004


def test_sync_show_titles(tmp_path):
    (tmp_path / "entries").mkdir()
    for ep in (351, 352, 90000):
        (tmp_path / "entries" / f"ep{ep:04d}.jsonl").write_text("{}\n")
    bili = tmp_path / "bili.json"
    bili.write_text(
        json.dumps(
            [
                {"n": 352, "share": "《这就是中国》第352集 中国社科研究的进展"},
                {"n": 353, "share": "《这就是中国》第353集 未来"},
            ]
        ),
        "utf-8",
    )
    assert sources.sync_show(tmp_path, bili) == 1  # 351 has no title, 90000 is not the show
    assert sources.read(tmp_path, 352) == {"kind": "ztjzg", "title": "中国社科研究的进展"}
    assert sources.sync_show(tmp_path, bili) == 0


def test_relabel_moves_an_episode_to_its_real_number(tmp_path):
    for d in ("entries", "frames", "vectors"):
        (tmp_path / d).mkdir()
    rows = [
        {"ep": 253, "t": 1, "text": "甲", "off": 0, "len": 3},
        {"ep": 253, "t": 2, "text": "乙", "off": 3, "len": 2},
    ]
    (tmp_path / "entries/ep0253.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), "utf-8"
    )
    (tmp_path / "frames/ep0253.pack").write_bytes(b"AAABB")
    (tmp_path / "vectors/ep0253.f16").write_bytes(b"VV")
    sources.write(tmp_path, 253, "ztjzg", title="旧标题")
    assert sources.relabel(tmp_path, 253, 198) == 2
    moved = [
        json.loads(line)
        for line in (tmp_path / "entries/ep0198.jsonl").read_text("utf-8").splitlines()
    ]
    assert [r["ep"] for r in moved] == [198, 198] and [r["text"] for r in moved] == ["甲", "乙"]
    assert (tmp_path / "frames/ep0198.pack").read_bytes() == b"AAABB"
    assert (tmp_path / "vectors/ep0198.f16").read_bytes() == b"VV"
    assert not list(tmp_path.rglob("ep0253*")) and not list(tmp_path.rglob("*.tmp"))
    (tmp_path / "entries/ep0300.jsonl").write_text("{}\n")
    with pytest.raises(FileExistsError):
        sources.relabel(tmp_path, 198, 300)  # never overwrite an existing episode
