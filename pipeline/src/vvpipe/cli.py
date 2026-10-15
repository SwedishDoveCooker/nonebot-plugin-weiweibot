"""Command line entry point: vvpipe ref | extract."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from . import extract as ex
from . import subtitle
from .faces import FaceMatcher, build_prototype

DEFAULT_MODELS = Path("models")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="vvpipe")
    ap.add_argument("--models", type=Path, default=DEFAULT_MODELS)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ref", help="build the target face prototype from a zip of face images")
    p.add_argument("--zip", type=Path, required=True)
    p.add_argument("--out", type=Path, default=DEFAULT_MODELS / "ref.npz")

    p = sub.add_parser("extract", help="index one episode video")
    p.add_argument("video", type=Path)
    p.add_argument("--ep", type=int, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--ref", type=Path, default=DEFAULT_MODELS / "ref.npz")
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("backfill", help="download and index a range of episodes, gently")
    p.add_argument("--first", type=int, required=True, help="newest episode to start from")
    p.add_argument("--last", type=int, required=True, help="oldest episode to stop at")
    p.add_argument("--map", type=Path, required=True, help="episode_map.json")
    p.add_argument("--cookies", type=Path, help="Netscape cookies file")
    p.add_argument("--firefox-profile", type=Path, help="live Firefox profile dir for cookies")
    p.add_argument("--rate-limit-mb", type=float, default=0, help="MB/s, 0 means unlimited")
    p.add_argument("--botcheck-wait-min", type=float, default=0, help="wait and retry on bot-check")
    p.add_argument("--botcheck-retries", type=int, default=20)
    p.add_argument("--player-client", help="yt-dlp YouTube player client, e.g. web_safari")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--ref", type=Path, default=DEFAULT_MODELS / "ref.npz")
    p.add_argument("--push", help="user@host:/remote/index/dir to copy finished episodes to")
    p.add_argument("--key", type=Path, help="ssh key for --push")
    p.add_argument("--max-per-day", type=int, default=120)
    p.add_argument("--pause", type=int, nargs=2, default=(30, 75), metavar=("MIN", "MAX"))

    p = sub.add_parser("import", help="index videos you downloaded yourself into a folder")
    p.add_argument("folder", type=Path)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--ref", type=Path, default=DEFAULT_MODELS / "ref.npz")
    p.add_argument("--bili", type=Path, help="episodes_bili.json, to recognise episodes by title")
    p.add_argument("--push", help="user@host:/remote/index/dir to copy finished episodes to")
    p.add_argument("--key", type=Path, help="ssh key for --push")
    p.add_argument("--watch", action="store_true", help="keep running and pick up new files")

    p = sub.add_parser("daemon", help="run the updater next to the bot (jobs + inbox -> index)")
    p.add_argument("--index", type=Path, required=True, help="the live index dir")
    p.add_argument("--inbox", type=Path, required=True)
    p.add_argument("--jobs", type=Path, required=True)
    p.add_argument("--notify", type=Path, required=True, help="the bot's notify dir")
    p.add_argument("--ref", type=Path, default=DEFAULT_MODELS / "ref.npz")
    p.add_argument("--bili", type=Path, help="episodes_bili.json, to recognise episodes by title")
    p.add_argument("--cookies", type=Path, help="cookies saved by the bot's /auth")
    p.add_argument(
        "--proxy",
        default=os.environ.get("VV_PROXY") or None,
        help="proxy that reaches YouTube, e.g. socks5://127.0.0.1:1080 (default: $VV_PROXY)",
    )
    p.add_argument("--poll", type=int, default=30)
    p.add_argument("--bili-mid", type=int, default=int(os.environ.get("VV_BILI_MID") or 0))
    p.add_argument("--bili-keyword", default=os.environ.get("VV_BILI_KEYWORD", "张维为"))
    p.add_argument("--bili-work", type=Path, help="state and downloads of the Bilibili account")
    p.add_argument(
        "--embed-url",
        default=os.environ.get("VV_EMBED_URL") or None,
        help="embed-serve address; new episodes then get sentence vectors (default: $VV_EMBED_URL)",
    )

    p = sub.add_parser("embed", help="compute sentence vectors for every indexed episode")
    p.add_argument("--index", type=Path, required=True)
    p.add_argument("--model", type=Path, default=DEFAULT_MODELS / "bge")
    p.add_argument("--threads", type=int)

    p = sub.add_parser("embed-serve", help="local HTTP service that embeds search queries")
    p.add_argument("--model", type=Path, default=DEFAULT_MODELS / "bge")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--threads", type=int)

    p = sub.add_parser(
        "bili-backfill", help="index every video of a Bilibili account (guest 1080p)"
    )
    p.add_argument("--mid", type=int, default=1458767615)
    p.add_argument(
        "--keyword", default="张维为", help="the account's name, used to find its videos"
    )
    p.add_argument("--since", default="2019-01-01")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--ref", type=Path, default=DEFAULT_MODELS / "ref.npz")
    p.add_argument("--push", help="user@host:/remote/index/dir (as for backfill)")
    p.add_argument("--key", type=Path)
    p.add_argument("--limit", type=int, help="stop after this many videos")
    p.add_argument("--relist", action="store_true", help="ignore the cached video list")
    p.add_argument("--list-only", action="store_true")
    p = sub.add_parser(
        "legacy-import", help="add the old nonebot-plugin-weiweibot pictures (assets.tar.gz)"
    )
    p.add_argument("--tar", type=Path, required=True)
    p.add_argument("--index", type=Path, required=True)
    p.add_argument("--force", action="store_true")

    p = sub.add_parser(
        "sources-sync", help="write source records (title of each episode of the show)"
    )
    p.add_argument("--index", type=Path, required=True)
    p.add_argument("--bili", type=Path, required=True, help="episodes_bili.json")

    p = sub.add_parser("notify", help="send a text to the bot's admin group")
    p.add_argument("text")
    p.add_argument("--push", required=True, help="user@host:/remote/index/dir (as for backfill)")
    p.add_argument("--key", type=Path, required=True)

    args = ap.parse_args(argv)
    if args.cmd in ("embed", "embed-serve"):
        from . import embed as em

        embedder = em.Embedder(args.model, args.threads)
        if args.cmd == "embed":
            print(json.dumps({"vectors_written": em.embed_missing(args.index, embedder)}))
            return 0
        em.serve(embedder, port=args.port)
        return 0
    if args.cmd == "daemon":
        from .daemon import Config, Daemon
        from .weekly_fetch import make_fetcher

        cfg = Config(
            index=args.index, inbox=args.inbox, jobs=args.jobs, notify=args.notify,
            models=args.models, ref=args.ref, bili=args.bili, cookies=args.cookies,
            proxy=args.proxy, poll=args.poll, embed_url=args.embed_url,
            bili_mid=args.bili_mid, bili_keyword=args.bili_keyword, bili_work=args.bili_work,
        )  # fmt: skip
        Daemon(cfg, fetcher=make_fetcher(cfg)).run()
        return 0
    if args.cmd == "bili-backfill":
        import datetime as dt
        import time

        from . import bili_fetch as bf
        from . import bili_ingest as bi
        from .backfill import Push

        args.work.mkdir(parents=True, exist_ok=True)
        cache = args.work / "bili_list.json"
        session = bf.Session()
        fresh = cache.exists() and time.time() - cache.stat().st_mtime < 86400 and not args.relist
        if fresh:
            videos = [bf.Video(**v) for v in json.loads(cache.read_text("utf-8"))]
        else:
            since = dt.date.fromisoformat(args.since)
            videos = session.list_all(args.mid, args.keyword, since)
            cache.write_text(json.dumps([v.__dict__ for v in videos], ensure_ascii=False), "utf-8")
        hours = sum(v.length_s for v in videos) / 3600
        print(json.dumps({"videos": len(videos), "hours": round(hours, 1)}))
        if args.list_only:
            return 0
        push = Push(args.push, args.key) if args.push else None
        state = bi.State.load(args.work / "bili_state.json")

        def pushed(video, ids):
            if push:
                for ep in ids:
                    push.send(args.out, ep)

        counts = bi.run(
            session, videos, state, args.out, args.work,
            FaceMatcher(args.models, args.ref), subtitle.Reader(),
            on_done=pushed, stop_after=args.limit,
        )  # fmt: skip
        print(json.dumps(counts))
        return 0
    if args.cmd == "legacy-import":
        from . import legacy

        print(
            json.dumps(
                legacy.import_tar(args.tar, args.index, force=args.force), ensure_ascii=False
            )
        )
        return 0
    if args.cmd == "sources-sync":
        from . import sources

        print(json.dumps({"written": sources.sync_show(args.index, args.bili)}))
        return 0
    if args.cmd == "notify":
        from .backfill import Push

        Push(args.push, args.key).notify(args.text)
        return 0
    if args.cmd == "ref":
        print(json.dumps(build_prototype(args.models, args.zip, args.out)))
        return 0
    if args.cmd == "extract":
        matcher = FaceMatcher(args.models, args.ref)
        reader = subtitle.Reader()
        print(
            json.dumps(
                ex.extract_episode(
                    args.video, args.ep, args.out, matcher, reader, force=args.force
                ),
                ensure_ascii=False,
            )
        )
        return 0
    if args.cmd == "import":
        import time

        from .backfill import Push
        from .importer import import_once, load_titles

        matcher, reader = FaceMatcher(args.models, args.ref), subtitle.Reader()
        titles = load_titles(args.bili)
        push = Push(args.push, args.key) if args.push else None
        while True:
            import_once(args.folder, args.out, matcher, reader, titles, push)
            if not args.watch:
                return 0
            time.sleep(30)
    if args.cmd == "backfill":
        from .backfill import Push, run

        raw = json.loads(args.map.read_text("utf-8"))
        mapping = {int(k): v["id"] for k, v in raw.items()}
        step = -1 if args.first >= args.last else 1
        episodes = list(range(args.first, args.last + step, step))
        push = Push(args.push, args.key) if args.push else None
        return run(
            episodes, mapping, args.cookies, args.out, args.work,
            FaceMatcher(args.models, args.ref), subtitle.Reader(), push,
            max_per_day=args.max_per_day, pause=tuple(args.pause),
            browser_profile=args.firefox_profile,
            botcheck_wait_min=args.botcheck_wait_min,
            botcheck_retries=args.botcheck_retries,
            player_client=args.player_client,
            rate=int(args.rate_limit_mb * 1024 * 1024) or None,
        )  # fmt: skip
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
