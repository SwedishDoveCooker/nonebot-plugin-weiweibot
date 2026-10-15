import json
from pathlib import Path

import pytest

from vvpipe import daemon


@pytest.fixture
def cfg(tmp_path):
    c = daemon.Config(
        index=tmp_path / "index",
        inbox=tmp_path / "inbox",
        jobs=tmp_path / "jobs",
        notify=tmp_path / "notify",
        models=tmp_path / "models",
        ref=tmp_path / "ref.npz",
    )
    c.jobs.mkdir()
    c.inbox.mkdir()
    return c


def _job(cfg, ep):
    (cfg.jobs / f"ep{ep:04d}.json").write_text(json.dumps({"ep": ep, "title": "x"}), "utf-8")


def _notes(cfg):
    if not cfg.notify.exists():
        return []
    return sorted(p.read_text("utf-8") for p in cfg.notify.glob("*.txt"))


def test_drop_note_is_atomic_and_readable(cfg):
    daemon.drop_note(cfg.notify, "你好")
    assert _notes(cfg) == ["你好"]
    assert not list(cfg.notify.glob("*.tmp"))


def test_job_for_an_already_indexed_episode_is_closed(cfg):
    (cfg.index / "entries").mkdir(parents=True)
    (cfg.index / "entries" / "ep0353.jsonl").write_text("{}\n")
    _job(cfg, 353)
    daemon.Daemon(cfg).tick()
    assert (cfg.jobs / "done" / "ep0353.json").exists()
    assert not (cfg.jobs / "ep0353.json").exists()


def test_without_a_fetcher_the_owner_is_told_once(cfg):
    _job(cfg, 353)
    d = daemon.Daemon(cfg)
    d.tick()
    d.tick()
    notes = _notes(cfg)
    assert len(notes) == 1 and "收件文件夹" in notes[0]
    assert (cfg.jobs / "ep0353.json").exists()  # still pending, nothing lost


def test_fetcher_is_retried_not_more_often_than_every_half_hour(cfg):
    _job(cfg, 353)
    calls = []

    def failing(job):
        calls.append(job["ep"])
        raise RuntimeError("not on YouTube yet")

    d = daemon.Daemon(cfg, fetcher=failing)
    d.tick()
    d.tick()
    assert calls == [353]
    assert len(_notes(cfg)) == 1


def test_unreadable_job_file_does_not_break_the_round(cfg):
    (cfg.jobs / "ep0001.json").write_text("{not json")
    assert daemon.Daemon(cfg).pending_jobs() == []
    assert Path(cfg.jobs / "ep0001.json").exists()
