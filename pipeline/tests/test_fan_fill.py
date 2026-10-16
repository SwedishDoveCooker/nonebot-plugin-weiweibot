import io
import json
from pathlib import Path

from vvpipe import bili_fetch as bf
from vvpipe import fan_fill


def _vv(tmp_path: Path, rows: list[tuple[int, str]]) -> Path:
    path = tmp_path / "vv.json"
    path.write_text(
        json.dumps(
            [{"filename": f"[P{n}]{n} 标题", "text": t, "timestamp": "0m01s"} for n, t in rows],
            ensure_ascii=False,
        ),
        "utf-8",
    )
    return path


def _episode(index: Path, ep: int, texts: list[str]) -> None:
    (index / "entries").mkdir(parents=True, exist_ok=True)
    (index / "entries" / f"ep{ep:04d}.jsonl").write_text(
        "".join(
            json.dumps({"ep": ep, "t": i, "text": t}, ensure_ascii=False) + "\n"
            for i, t in enumerate(texts)
        ),
        "utf-8",
    )


def test_vv_lines_are_per_episode_and_ignore_short_ones(tmp_path):
    path = _vv(tmp_path, [(5, "这是第五期的一句话"), (5, "短"), (6, "这是第六期的话语")])
    assert fan_fill.vv_lines(path, 5) == {fan_fill.norm("这是第五期的一句话")}
    assert fan_fill.vv_lines(path, 7) == set()


def test_accept_by_overlap_with_vv(tmp_path):
    ref = {
        fan_fill.norm(t)
        for t in ("第一句话比较长一点", "第二句话也比较长", "第三句话同样很长", "第四句话还是很长")
    }
    _episode(
        tmp_path,
        5,
        ["第一句话比较长一点", "第二句话也比较长", "第三句话同样很长", "无关的内容在这里"],
    )
    ok, why = fan_fill.accept(tmp_path, 5, ref, 2000, None)
    assert ok and "75%" in why
    _episode(tmp_path, 6, ["完全不同的内容一", "完全不同的内容二", "第一句话比较长一点"])
    assert not fan_fill.accept(tmp_path, 6, ref, 2000, None)[0]  # a different episode


def test_accept_by_length_when_vv_does_not_cover_the_episode(tmp_path):
    _episode(tmp_path, 300, ["随便一句话"])
    assert fan_fill.accept(tmp_path, 300, set(), 2350, 2352)[0]
    assert not fan_fill.accept(tmp_path, 300, set(), 1500, 2352)[0]  # cut down
    assert not fan_fill.accept(tmp_path, 300, set(), 2350, None)[0]  # nothing to compare with


def test_adopt_copies_pack_source_and_index_last(tmp_path):
    staged, final = tmp_path / "stage", tmp_path / "out"
    for sub, name in (
        ("frames", "ep0007.pack"),
        ("sources", "ep0007.json"),
        ("entries", "ep0007.jsonl"),
    ):
        (staged / sub).mkdir(parents=True)
        (staged / sub / name).write_text(sub)
    fan_fill.adopt(staged, final, 7)
    assert (final / "entries" / "ep0007.jsonl").read_text() == "entries"
    assert (final / "frames" / "ep0007.pack").read_text() == "frames"
    assert not list(final.rglob("*.tmp"))


class FakeSession:
    pass


def test_run_takes_the_verified_upload_and_skips_a_wrong_one(tmp_path, monkeypatch):
    ref_texts = ["参考的第一句话很长", "参考的第二句话很长", "参考的第三句话很长"]
    vv = _vv(tmp_path, [(5, t) for t in ref_texts])
    served = {"BVBAD": ["别的期数一", "别的期数二", "别的期数三"], "BVGOOD": ref_texts}

    def fake_download(session, bvid, dest, **kw):
        dest.mkdir(parents=True, exist_ok=True)
        f = dest / f"{bvid}.mkv"
        f.write_text("x")
        return f

    def fake_extract(video, ep, out, matcher, reader, **kw):
        _episode(out, ep, served[video.stem])
        (out / "frames").mkdir(parents=True, exist_ok=True)
        (out / "frames" / f"ep{ep:04d}.pack").write_bytes(b"jpg")
        return {"lines": 3}

    monkeypatch.setattr(fan_fill.bf, "download", fake_download)
    monkeypatch.setattr(fan_fill.ex, "extract_episode", fake_extract)
    monkeypatch.setattr(fan_fill, "ex_duration", lambda v: 2000.0)
    cands = {5: [{"bvid": "BVBAD", "title": "错的"}, {"bvid": "BVGOOD", "title": "对的"}]}
    counts = fan_fill.run(
        cands, FakeSession(), tmp_path / "out", tmp_path / "work", vv, {}, None, None,
        {5: "标题"}, log=io.StringIO(),
    )  # fmt: skip
    assert counts == {"rejected": 1, "accepted": 1}
    assert (tmp_path / "out" / "entries" / "ep0005.jsonl").exists()
    assert (
        json.loads((tmp_path / "out" / "sources" / "ep0005.json").read_text("utf-8"))["id"]
        == "BVGOOD"
    )
    state = json.loads((tmp_path / "work" / "fan_state.json").read_text("utf-8"))
    assert state["5"]["ok"] and state["5"]["tried"] == ["BVBAD", "BVGOOD"]
    assert counts and bf  # imported for the monkeypatch above
