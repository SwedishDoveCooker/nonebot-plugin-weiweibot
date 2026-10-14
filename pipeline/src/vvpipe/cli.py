"""Command line entry point: vvpipe ref | extract."""

from __future__ import annotations

import argparse
import json
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
    p.add_argument("--cookies", type=Path, required=True)
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

    args = ap.parse_args(argv)
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
        )  # fmt: skip
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
