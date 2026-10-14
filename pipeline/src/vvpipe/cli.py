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
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
