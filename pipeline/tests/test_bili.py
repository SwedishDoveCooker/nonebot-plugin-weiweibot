import datetime as dt
import json

import pytest

from vvpipe import bili_fetch as bf
from vvpipe import bili_ingest as bi
from vvpipe import sources


def test_windows_cover_the_range_without_gaps_or_overlap():
    ws = bf.windows(dt.date(2026, 1, 1), dt.date(2026, 3, 15), 30)
    assert ws[0][0] == dt.datetime(2026, 1, 1)
    assert ws[-1][1] == dt.datetime(2026, 3, 15, 23, 59, 59)
    for (_, end), (begin, _) in zip(ws, ws[1:], strict=False):
        assert begin - end == dt.timedelta(seconds=1)
    assert bf.windows(dt.date(2026, 5, 1), dt.date(2026, 5, 1), 30) == [
        (dt.datetime(2026, 5, 1), dt.datetime(2026, 5, 1, 23, 59, 59))
    ]


def test_search_rows_become_videos():
    v = bf.video_from_search(
        {
            "bvid": "BV1x",
            "title": '<em class="keyword">张维为</em>讲&amp;谈',
            "duration": "1:02:03",
            "pubdate": 0,
        }
    )
    assert v.bvid == "BV1x" and v.title == "张维为讲&谈" and v.length_s == 3723


def _dash(*items):
    return {
        "video": [
            {"height": h, "codecid": c, "bandwidth": b, "baseUrl": f"v{h}-{c}"} for h, c, b in items
        ],
        "audio": [
            {"id": 1, "bandwidth": 100, "baseUrl": "a1"},
            {"id": 2, "bandwidth": 300, "baseUrl": "a2"},
        ],
    }


def test_pick_streams_prefers_h264_1080p_and_the_best_audio():
    video, audio = bf.pick_streams(
        _dash((480, 7, 9), (1080, 12, 500), (1080, 7, 400), (1080, 13, 300))
    )
    assert (video["height"], video["codecid"]) == (1080, 7)
    assert audio["baseUrl"] == "a2"


def test_pick_streams_never_settles_for_less_than_1080p():
    with pytest.raises(bf.NoHighQuality):
        bf.pick_streams(_dash((360, 7, 1), (480, 7, 2), (720, 7, 3)))


def test_urls_of_lists_the_backups_too():
    assert bf.urls_of({"baseUrl": "a", "backupUrl": ["b", "c"]}) == ["a", "b", "c"]
    assert bf.urls_of({"base_url": "a", "backup_url": None}) == ["a"]


class FakeSession:
    def __init__(self, parts=1):
        self.n_parts = parts

    def parts(self, bvid):
        return [{"cid": i, "part": f"p{i}"} for i in range(self.n_parts)]


@pytest.fixture
def fakes(monkeypatch, tmp_path):
    calls = {"download": [], "extract": []}

    def fake_download(session, bvid, dest, part_index=0, log=None):
        dest.mkdir(parents=True, exist_ok=True)
        f = dest / f"{bvid}_{part_index}.mkv"
        f.write_bytes(b"x")
        calls["download"].append((bvid, part_index))
        if bvid == "LOWRES":
            raise bf.NoHighQuality("no 1080p")
        if bvid == "BROKEN":
            raise RuntimeError("disk on fire")
        return f

    def fake_extract(video, ep, out_dir, matcher, reader, **kw):
        calls["extract"].append(ep)
        (out_dir / "entries").mkdir(parents=True, exist_ok=True)
        (out_dir / "entries" / f"ep{ep:04d}.jsonl").write_text("{}\n")
        return {"lines": 1}

    monkeypatch.setattr(bi.bf, "download", fake_download)
    monkeypatch.setattr(bi.ex, "extract_episode", fake_extract)
    return calls, tmp_path


def _video(bvid, length=300):
    return bf.Video(bvid, f"title {bvid}", length, "2026-01-02")


def test_run_indexes_records_sources_and_removes_the_download(fakes):
    calls, tmp = fakes
    out, work = tmp / "out", tmp / "work"
    state = bi.State.load(tmp / "state.json")
    done = []
    counts = bi.run(
        FakeSession(), [_video("BV1"), _video("BV2")], state, out, work, None, None,
        on_done=lambda v, ids: done.append((v.bvid, ids)), log=lambda m: None,
    )  # fmt: skip
    assert counts["done"] == 2 and done == [("BV1", [10000]), ("BV2", [10001])]
    assert sources.read(out, 10000) == {
        "kind": "bili",
        "title": "title BV1",
        "id": "BV1",
        "pub": "2026-01-02",
    }
    assert not list((work / "dl").glob("*.mkv"))
    assert json.loads((tmp / "state.json").read_text("utf-8"))["videos"]["BV1"]["status"] == "done"


def test_a_second_run_skips_what_is_done(fakes):
    calls, tmp = fakes
    state = bi.State.load(tmp / "state.json")
    args = (state, tmp / "out", tmp / "work", None, None)
    bi.run(FakeSession(), [_video("BV1")], *args, log=lambda m: None)
    bi.run(FakeSession(), [_video("BV1")], *args, log=lambda m: None)
    assert calls["download"] == [("BV1", 0)]


def test_low_resolution_and_failures_do_not_stop_the_run(fakes):
    calls, tmp = fakes
    state = bi.State.load(tmp / "state.json")
    videos = [_video("LOWRES"), _video("BROKEN"), _video("OK")]
    counts = bi.run(
        FakeSession(), videos, state, tmp / "out", tmp / "work", None, None, log=lambda m: None
    )
    assert counts == {"done": 1, "lowres": 1, "failed": 1, "skipped": 0}
    assert state.get("LOWRES")["status"] == "lowres" and state.get("BROKEN")["tries"] == 1
    assert calls["extract"] == [10000]  # only the good one was indexed


def test_a_video_is_given_up_after_a_few_failures(fakes):
    calls, tmp = fakes
    state = bi.State.load(tmp / "state.json")
    for _ in range(bi.RETRIES_PER_VIDEO + 2):
        bi.run(
            FakeSession(),
            [_video("BROKEN")],
            state,
            tmp / "out",
            tmp / "work",
            None,
            None,
            log=lambda m: None,
        )
    assert calls["download"].count(("BROKEN", 0)) == bi.RETRIES_PER_VIDEO


def test_multi_part_videos_get_one_id_per_part_and_resume(fakes):
    calls, tmp = fakes
    state = bi.State.load(tmp / "state.json")
    state.set("BV1", ids=[10000])  # part 1 was done by an interrupted run
    (tmp / "out" / "entries").mkdir(parents=True)
    (tmp / "out" / "entries" / "ep10000.jsonl").write_text("{}\n")
    bi.run(
        FakeSession(parts=2),
        [_video("BV1")],
        state,
        tmp / "out",
        tmp / "work",
        None,
        None,
        log=lambda m: None,
    )
    assert calls["download"] == [("BV1", 1)]
    assert state.get("BV1")["ids"] == [10000, 10001]
    assert sources.read(tmp / "out", 10001)["title"].startswith("title BV1 P2")


def test_very_long_videos_are_skipped(fakes):
    calls, tmp = fakes
    state = bi.State.load(tmp / "state.json")
    counts = bi.run(
        FakeSession(),
        [_video("BIG", length=5 * 3600)],
        state,
        tmp / "out",
        tmp / "work",
        None,
        None,
        log=lambda m: None,
    )
    assert counts["skipped"] == 1 and calls["download"] == []
