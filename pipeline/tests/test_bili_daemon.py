from pathlib import Path

from vvpipe import bili_fetch as bf
from vvpipe import bili_ingest as bi
from vvpipe import daemon, faces, subtitle


class FakeSession:
    searches = 0

    def search_window(self, mid, keyword, begin, end):
        FakeSession.searches += 1
        return [bf.Video("BV1", "新视频", 300, "2026-10-15")]


def _daemon(tmp_path, monkeypatch, mid=7):
    FakeSession.searches = 0
    monkeypatch.setattr(bf, "Session", FakeSession)
    monkeypatch.setattr(faces, "FaceMatcher", lambda *a, **k: object())
    monkeypatch.setattr(subtitle, "Reader", lambda *a, **k: object())
    monkeypatch.setattr(daemon.Daemon, "embed_vectors", lambda self: 0)

    def fake_run(session, videos, state, out, work, matcher, reader, on_done=None, **kw):
        for v in videos:
            state.set(v.bvid, status="done")
            on_done(v, [10000])
        return {"done": len(videos), "lowres": 0, "failed": 0, "skipped": 0}

    monkeypatch.setattr(bi, "run", fake_run)
    cfg = daemon.Config(
        index=tmp_path / "index", inbox=tmp_path / "inbox", jobs=tmp_path / "jobs",
        notify=tmp_path / "notify", models=Path("m"), ref=Path("r"),
        bili_mid=mid, bili_keyword="张维为", bili_work=tmp_path / "work",
    )  # fmt: skip
    return daemon.Daemon(cfg)


def test_new_videos_are_indexed_and_announced(tmp_path, monkeypatch):
    d = _daemon(tmp_path, monkeypatch)
    d.bili_check()
    notes = [p.read_text("utf-8") for p in (tmp_path / "notify").glob("*.txt")]
    assert len(notes) == 1 and "新视频" in notes[0]


def test_it_looks_only_about_once_a_day(tmp_path, monkeypatch):
    d = _daemon(tmp_path, monkeypatch)
    d.bili_check()
    d.bili_check()
    assert FakeSession.searches == 1


def test_it_is_off_without_an_account(tmp_path, monkeypatch):
    d = _daemon(tmp_path, monkeypatch, mid=0)
    d.bili_check()
    assert FakeSession.searches == 0
