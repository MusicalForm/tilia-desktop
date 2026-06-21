#!/usr/bin/env python3
"""Re-vendor the LCMA web assets from the annotation-ui repo into this fork.

Two build artifacts from the annotation-ui project are vendored into TiLiA:

    dist-embed/embed.html      ->  tilia/ui/timelines/lcma/builder/embed.html
    src/generated/vocab.json   ->  tilia/ui/timelines/lcma/vocab.json

``embed.html`` is the single-file QWebEngine builder; ``vocab.json`` gives ``span_view`` the
ontology abbreviations. Both are generated, so they drift whenever the annotation-ui ontology
or builder changes. Keeping them in the repo (rather than building at install time) keeps the
desktop build self-contained, but it has to be refreshed by hand — this script is that hand.

Usage::

    python scripts/sync_lcma_assets.py [--source PATH] [--build] [--check]

    --source PATH   annotation-ui repo (default: $LCMA_ANNOTATION_UI or ../lcma-annotation-ui)
    --build         run `npm run build:embed` and `npm run ontology:gen` in the source first
    --check         do not copy; exit 1 if any vendored file differs (a CI / pre-commit gate)
"""

from __future__ import annotations

import argparse
import filecmp
import os
import shutil
import subprocess
import sys
from pathlib import Path

FORK_ROOT = Path(__file__).resolve().parent.parent

# (path of the artifact within the annotation-ui repo, destination within this fork)
ASSETS = [
    ("dist-embed/embed.html", FORK_ROOT / "tilia/ui/timelines/lcma/builder/embed.html"),
    ("src/generated/vocab.json", FORK_ROOT / "tilia/ui/timelines/lcma/vocab.json"),
]

# Commands that (re)generate the artifacts above, run in the annotation-ui repo with --build.
BUILD_COMMANDS = [
    ["npm", "run", "build:embed"],  # -> dist-embed/embed.html
    ["npm", "run", "ontology:gen"],  # -> src/generated/vocab.json
]


def resolve_source(arg: str | None) -> Path:
    raw = (
        arg
        or os.environ.get("LCMA_ANNOTATION_UI")
        or str(FORK_ROOT.parent / "lcma-annotation-ui")
    )
    src = Path(raw).expanduser().resolve()
    if not src.is_dir():
        sys.exit(
            f"annotation-ui source not found: {src}\n"
            "pass --source PATH or set LCMA_ANNOTATION_UI"
        )
    return src


def run_build(source: Path) -> None:
    for cmd in BUILD_COMMANDS:
        print(f"$ ({source}) {' '.join(cmd)}")
        subprocess.run(cmd, cwd=source, check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--source", help="path to the annotation-ui repo")
    ap.add_argument(
        "--build",
        action="store_true",
        help="rebuild the artifacts in the source repo first",
    )
    ap.add_argument(
        "--check",
        action="store_true",
        help="do not copy; exit 1 if any vendored file is stale",
    )
    args = ap.parse_args()

    source = resolve_source(args.source)
    if args.build:
        run_build(source)

    missing = [rel for rel, _ in ASSETS if not (source / rel).is_file()]
    if missing:
        hint = "" if args.build else " (run with --build, or build the source first)"
        sys.exit(f"source artifact(s) missing: {', '.join(missing)}{hint}")

    stale = []
    for rel, dest in ASSETS:
        src_file = source / rel
        same = dest.is_file() and filecmp.cmp(src_file, dest, shallow=False)
        rel_dest = dest.relative_to(FORK_ROOT)
        if args.check:
            print(f"[{'ok' if same else 'STALE'}] {rel_dest}  <-  {rel}")
            if not same:
                stale.append(rel)
        elif same:
            print(f"[unchanged] {rel_dest}")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src_file, dest)
            print(f"[vendored]  {rel_dest}  <-  {rel}")

    if args.check and stale:
        print(
            f"\n{len(stale)} vendored asset(s) are stale. Run:\n"
            "  python scripts/sync_lcma_assets.py --build\n"
            "and commit the result.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
