from pathlib import Path

import pytest

from vvpipe import backfill, fetch


@pytest.fixture
def fakes(monkeypatch, tmp_path):
    done: list[int] = []
    calls: list[str] = []

    def fake_download(vid, dest, cookies=None, rate=None, browser_profile=None, player_client=None):
        calls.append(vid)
        if vid == "BOT":
            raise fetch.BotCheckError("sign in")
        dest.mkdir(parents=True, exist_ok=True)
        p = dest / f"{vid}.mkv"
        p.write_bytes(b"x")
        return p

    def fake_extract(video, ep, out_dir, matcher, reader, log=None, force=False):
        (out_dir / "entries").mkdir(parents=True, exist_ok=True)
        (out_dir / "entries" / f"ep{ep:04d}.jsonl").write_text("{}\n")
        done.append(ep)
        return {"ep": ep, "lines": 1}

    monkeypatch.setattr(fetch, "download", fake_download)
    monkeypatch.setattr(fetch, "duration_seconds", lambda p: 2000.0)
    monkeypatch.setattr(backfill.ex, "extract_episode", fake_extract)
    return done, calls, tmp_path


def _run(tmp_path, episodes, mapping, **kw):
    return backfill.run(
        episodes, mapping, Path("c"), tmp_path / "out", tmp_path / "work", None, None,
        pause=(0, 0), **kw,
    )  # fmt: skip


def test_all_episodes_extracted_in_order_and_videos_removed(fakes):
    done, _, tmp = fakes
    code = _run(tmp, [3, 2, 1], {1: "a", 2: "b", 3: "c"})
    assert code == 0
    assert done == [3, 2, 1]
    assert not list((tmp / "work" / "dl").glob("*.mkv"))


def test_bot_check_stops_downloads_but_queued_work_finishes(fakes):
    done, calls, tmp = fakes
    code = _run(tmp, [4, 3, 2, 1], {4: "a", 3: "b", 2: "BOT", 1: "d"})
    assert code == 3
    assert calls == ["a", "b", "BOT"]  # never asked for episode 1 after the bot-check
    assert done == [4, 3]  # what was already downloaded still got indexed


def test_bot_check_is_waited_out_and_the_same_episode_retried(fakes, monkeypatch):
    done, calls, tmp = fakes
    state = {"blocked": 2}
    real = fetch.download

    def flaky(vid, dest, cookies=None, rate=None, browser_profile=None, player_client=None):
        if state["blocked"] > 0:
            state["blocked"] -= 1
            calls.append("blocked")
            raise fetch.BotCheckError("sign in")
        return real(vid, dest, cookies, rate, browser_profile, player_client)

    monkeypatch.setattr(fetch, "download", flaky)
    code = _run(tmp, [2, 1], {2: "b", 1: "a"}, botcheck_wait_min=0.0005, botcheck_retries=5)
    assert code == 0
    assert calls[:3] == ["blocked", "blocked", "b"]  # episode 2 retried, not skipped
    assert done == [2, 1]


def test_gives_up_after_the_retry_budget(fakes, monkeypatch):
    done, calls, tmp = fakes

    def always_blocked(
        vid, dest, cookies=None, rate=None, browser_profile=None, player_client=None
    ):
        calls.append(vid)
        raise fetch.BotCheckError("sign in")

    monkeypatch.setattr(fetch, "download", always_blocked)
    code = _run(tmp, [2, 1], {2: "b", 1: "a"}, botcheck_wait_min=0.0005, botcheck_retries=2)
    assert code == 3
    assert calls == ["b", "b", "b"]  # first try plus two retries
    assert done == []


def test_finished_and_unmapped_episodes_are_skipped(fakes):
    done, calls, tmp = fakes
    (tmp / "out" / "entries").mkdir(parents=True)
    (tmp / "out" / "entries" / "ep0003.jsonl").write_text("{}\n")
    code = _run(tmp, [3, 2, 1], {3: "c", 1: "a"})
    assert code == 0
    assert calls == ["a"]
    assert done == [1]
