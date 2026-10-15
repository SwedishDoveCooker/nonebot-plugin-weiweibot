"""The updater that runs next to the bot.

Jobs written by the bot (data/jobs/epNNNN.json) and videos dropped into data/inbox go in;
indexed episodes in the live index come out, and the admin group is told about it through
the bot's notify directory. Everything is restartable: a half-processed video stays in the
inbox, index files are renamed into place last.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import importer
from .faces import FaceMatcher
from .subtitle import Reader

FETCH_RETRY_SECONDS = 30 * 60
_JOB = re.compile(r"^ep(\d{4})\.json$")


def drop_note(notify_dir: Path, text: str) -> None:
    """Hand a text to the bot, which forwards it to the admin group."""
    notify_dir.mkdir(parents=True, exist_ok=True)
    name = f"{int(time.time() * 1000)}"
    tmp = notify_dir / f"{name}.tmp"
    tmp.write_text(text, "utf-8")
    os.replace(tmp, notify_dir / f"{name}.txt")


@dataclass
class Config:
    index: Path
    inbox: Path
    jobs: Path
    notify: Path
    models: Path
    ref: Path
    bili: Path | None = None
    cookies: Path | None = None
    proxy: str | None = None
    poll: int = 30
    embed_url: str | None = None  # embed-serve; when set, new episodes get sentence vectors


@dataclass
class Daemon:
    cfg: Config
    fetcher: object | None = None  # callable(job: dict) -> None, set when downloading is possible
    _last_try: dict[int, float] = field(default_factory=dict)
    _told: set[int] = field(default_factory=set)

    def note(self, text: str) -> None:
        try:
            drop_note(self.cfg.notify, text)
        except OSError as err:
            print(f"cannot write a notification: {err}", file=sys.stderr)

    def mark_done(self, ep: int) -> None:
        src = self.cfg.jobs / f"ep{ep:04d}.json"
        done = self.cfg.jobs / "done"
        if src.exists():
            done.mkdir(parents=True, exist_ok=True)
            os.replace(src, done / src.name)

    def indexed(self, ep: int) -> bool:
        return (self.cfg.index / "entries" / f"ep{ep:04d}.jsonl").exists()

    def embed_vectors(self) -> int:
        """Give every indexed episode its sentence vectors; harmless when the service is down."""
        if not self.cfg.embed_url:
            return 0
        from .embed import RemoteEmbedder, embed_missing

        try:
            return embed_missing(self.cfg.index, RemoteEmbedder(self.cfg.embed_url), log=print)
        except Exception as err:  # noqa: BLE001 - text search keeps working without vectors
            print(f"vectors not updated: {err}", file=sys.stderr)
            return 0

    def pending_jobs(self) -> list[dict]:
        out = []
        for p in sorted(self.cfg.jobs.glob("ep*.json")) if self.cfg.jobs.exists() else []:
            if _JOB.match(p.name):
                try:
                    out.append(json.loads(p.read_text("utf-8")))
                except (OSError, ValueError):
                    print(f"unreadable job file {p.name}, ignored", file=sys.stderr)
        return out

    def tick(self) -> None:
        self.cfg.inbox.mkdir(parents=True, exist_ok=True)
        if importer.pending_videos(self.cfg.inbox):
            matcher = FaceMatcher(self.cfg.models, self.cfg.ref)
            reader = Reader()
            titles = importer.load_titles(self.cfg.bili)
            importer.import_once(
                self.cfg.inbox,
                self.cfg.index,
                matcher,
                reader,
                titles,
                notify=self.note,
                on_done=self.mark_done,
            )
            self.embed_vectors()
        for job in self.pending_jobs():
            ep = int(job["ep"])
            if self.indexed(ep):
                self.mark_done(ep)
                continue
            if importer.pending_videos(self.cfg.inbox):
                continue  # something is being processed; look again next round
            self.try_fetch(job)

    def try_fetch(self, job: dict) -> None:
        ep = int(job["ep"])
        if self.fetcher is None:
            if ep not in self._told:
                self._told.add(ep)
                self.note(
                    f"第 {ep} 集的更新任务已收到, 但这台机器还不能自己下载。"
                    f"请把 1080p 视频放进收件文件夹, 文件名带「第{ep}期」, 我会自动识别。"
                )
            return
        if time.time() - self._last_try.get(ep, 0) < FETCH_RETRY_SECONDS:
            return
        self._last_try[ep] = time.time()
        try:
            self.fetcher(job)  # type: ignore[operator]
        except Exception as err:  # noqa: BLE001 - keep the daemon alive, report once per hour
            print(f"ep{ep}: fetch failed: {err}", file=sys.stderr)
            if ep not in self._told:
                self._told.add(ep)
                self.note(f"第 {ep} 集暂时下不到: {str(err)[:120]}。会每 30 分钟重试。")

    def run(self) -> None:
        print("updater daemon started", file=sys.stderr, flush=True)
        self.embed_vectors()  # catch up on episodes that arrived without vectors
        while True:
            try:
                self.tick()
            except Exception as err:  # noqa: BLE001 - never let one bad round kill the service
                print(f"tick failed: {err!r}", file=sys.stderr, flush=True)
            time.sleep(self.cfg.poll)
