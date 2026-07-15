#!/usr/bin/env python3
"""Re-vendor the LCMA web assets from the annotation-ui repo into this fork.

Two build artifacts from the annotation-ui project are vendored into TiLiA:

    dist-embed/embed.html          ->  tilia/ui/timelines/lcma/builder/embed.html
    dist-validator/validator.html  ->  tilia/ui/timelines/lcma/validator/validator.html
    src/generated/vocab.json       ->  tilia/ui/timelines/lcma/vocab.json

``embed.html`` is the single-file QWebEngine builder and ``validator.html`` the headless
session-wide diagnostics engine (both loaded over file:// in a QWebEngine page); ``vocab.json``
gives ``span_view`` the ontology abbreviations. All are generated, so they drift whenever the
annotation-ui ontology or builder changes. Keeping them in the repo (rather than building at
install time) keeps the desktop build self-contained, but it has to be refreshed by hand — this
script is that hand.

There are two ways to vendor:

1. ``--from-release TAG`` (preferred) downloads the three assets from a published
   annotation-ui GitHub release. The bundles were built by CI from one tagged commit, so no
   local checkout, Node, or build is needed and the result is reproducible from the tag alone.
2. ``--source PATH`` copies the assets a local annotation-ui checkout has already built
   (optionally building them first with ``--build``). This is the escape hatch for vendoring an
   unreleased, work-in-progress source state.

Next to the assets it writes ``SOURCE.txt`` in each vendored directory — the annotation-ui
revision the bundle was built from — so a vendored file is traceable to a source revision. In
release mode the stamp records the release tag, source commit, and pinned ontology (read from
the release ``manifest.json``); in ``--source`` mode it records the commit, branch, and whether
that source tree was dirty (an unclean, non-reproducible vendor is then visible in the diff).

Usage::

    python scripts/sync_lcma_assets.py --from-release TAG [--repo OWNER/REPO] [--check]
    python scripts/sync_lcma_assets.py [--source PATH] [--build] [--check]

    --from-release TAG  vendor the assets from annotation-ui release TAG (via the `gh` CLI)
    --repo OWNER/REPO   annotation-ui GitHub repo for --from-release (default: MusicalForm/lcma-annotation-ui)
    --source PATH       annotation-ui repo (default: $LCMA_ANNOTATION_UI or ../lcma-annotation-ui)
    --build             run `npm run build:embed` and `npm run ontology:gen` in the source first
    --check             do not copy; exit 1 if any vendored file differs (a CI / pre-commit gate),
                        and report the provenance recorded in builder/SOURCE.txt
"""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FORK_ROOT = Path(__file__).resolve().parent.parent

# GitHub repo that publishes the annotation-ui release assets (for --from-release).
DEFAULT_REPO = "MusicalForm/lcma-annotation-ui"

# (path of the artifact within the annotation-ui repo, destination within this fork).
# In --from-release mode the release asset is the basename of the first element
# (e.g. dist-embed/embed.html -> the "embed.html" asset); the three basenames are distinct.
ASSETS = [
    ("dist-embed/embed.html", FORK_ROOT / "tilia/ui/timelines/lcma/builder/embed.html"),
    (
        "dist-validator/validator.html",
        FORK_ROOT / "tilia/ui/timelines/lcma/validator/validator.html",
    ),
    ("src/generated/vocab.json", FORK_ROOT / "tilia/ui/timelines/lcma/vocab.json"),
]

# Provenance manifest written next to the assets: which annotation-ui commit they came from.
# The embed and validator bundles are vendored from the same source tree in one run, so both
# directories get the same stamp (each vendored dir stays self-describing).
PROVENANCE_FILE = FORK_ROOT / "tilia/ui/timelines/lcma/builder/SOURCE.txt"
PROVENANCE_FILE_VALIDATOR = FORK_ROOT / "tilia/ui/timelines/lcma/validator/SOURCE.txt"

# Commands that (re)generate the artifacts above, run in the annotation-ui repo with --build.
BUILD_COMMANDS = [
    ["npm", "run", "build:embed"],  # -> dist-embed/embed.html
    ["npm", "run", "build:validator"],  # -> dist-validator/validator.html
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


def _git(source: Path, *args: str) -> str | None:
    try:
        return subprocess.run(
            ["git", "-C", str(source), *args],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None


def source_provenance(source: Path) -> dict[str, str]:
    """Describe the annotation-ui revision the vendored assets were built from."""
    commit = _git(source, "rev-parse", "HEAD")
    if commit is None:
        return {"commit": "unknown", "branch": "", "dirty": "unknown"}
    branch = _git(source, "rev-parse", "--abbrev-ref", "HEAD") or ""
    if branch == "HEAD":  # detached checkout (e.g. vendoring from a pinned worktree)
        branch = "(detached)"
    dirty = bool(_git(source, "status", "--porcelain"))
    return {"commit": commit, "branch": branch, "dirty": "true" if dirty else "false"}


def write_provenance(prov: dict[str, str], dest: Path = PROVENANCE_FILE) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        "# Provenance of the vendored LCMA assets in this directory.\n"
        "# Generated by scripts/sync_lcma_assets.py -- do not edit by hand.\n"
        "source_repo: lcma-annotation-ui\n"
        f"commit: {prov['commit']}\n"
        f"branch: {prov['branch']}\n"
        f"dirty: {prov['dirty']}\n",
        encoding="utf-8",
    )


def read_provenance(src: Path = PROVENANCE_FILE) -> dict[str, str]:
    prov: dict[str, str] = {}
    if src.is_file():
        for line in src.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and ":" in line:
                key, _, value = line.partition(":")
                prov[key.strip()] = value.strip()
    return prov


def _report_provenance(current: dict[str, str]) -> None:
    recorded = read_provenance()
    if not recorded:
        print(
            "[provenance] SOURCE.txt missing — vendored assets have no recorded origin"
        )
        return
    print(
        f"[provenance] vendored from commit {recorded.get('commit', '?')[:9]} "
        f"(dirty={recorded.get('dirty', '?')}); source now at {current['commit'][:9]}"
    )
    if recorded.get("dirty") == "true":
        print(
            "warning: recorded provenance is 'dirty' — the committed bundle was vendored from "
            "an unclean source tree and may not be reproducible.",
            file=sys.stderr,
        )


# --- release mode (--from-release) --------------------------------------------------------


def download_release(tag: str, repo: str) -> Path:
    """Download a published annotation-ui release's assets into a fresh temp dir."""
    tmp = Path(tempfile.mkdtemp(prefix="lcma-release-"))
    wanted = [Path(rel).name for rel, _ in ASSETS] + ["manifest.json"]
    cmd = ["gh", "release", "download", tag, "--repo", repo, "--dir", str(tmp)]
    for name in wanted:
        cmd += ["--pattern", name]
    print(f"$ {' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError:
        sys.exit(
            "the GitHub CLI ('gh') is required for --from-release but was not found.\n"
            "Install it (https://cli.github.com) or vendor from a checkout with --source."
        )
    except subprocess.CalledProcessError as exc:
        sys.exit(f"failed to download release {tag!r} from {repo}: {exc}")
    return tmp


def read_manifest(tmp: Path) -> dict:
    manifest = tmp / "manifest.json"
    if not manifest.is_file():
        sys.exit(
            "release is missing manifest.json — cannot record provenance. "
            "Was it published by the release-bundles workflow?"
        )
    return json.loads(manifest.read_text(encoding="utf-8"))


def release_provenance(manifest: dict, tag: str) -> dict[str, str]:
    """Describe the annotation-ui release the vendored assets were downloaded from."""
    ontology = manifest.get("ontology") or {}
    ontology_str = ""
    if ontology:
        commit = str(ontology.get("commit", ""))[:8]
        ontology_str = (
            f"{ontology.get('tag', '?')} ({commit})"
            if commit
            else str(ontology.get("tag", "?"))
        )
    return {
        "commit": manifest.get("commit", "unknown"),
        "release_tag": manifest.get("tag", tag),
        "ontology": ontology_str,
    }


def write_release_provenance(prov: dict[str, str], dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        "# Provenance of the vendored LCMA assets in this directory.\n"
        "# Generated by scripts/sync_lcma_assets.py --from-release -- do not edit by hand.\n"
        "source_repo: lcma-annotation-ui\n"
        f"release_tag: {prov['release_tag']}\n"
        f"commit: {prov['commit']}\n"
        f"ontology: {prov['ontology']}\n",
        encoding="utf-8",
    )


def _report_release_provenance(current: dict[str, str]) -> None:
    recorded = read_provenance()
    if not recorded:
        print(
            "[provenance] SOURCE.txt missing — vendored assets have no recorded origin"
        )
        return
    print(
        f"[provenance] vendored from release {recorded.get('release_tag', '?')} "
        f"(commit {recorded.get('commit', '?')[:9]}); checked against {current['release_tag']}"
    )


# --- shared copy/check loop ---------------------------------------------------------------


def process_assets(plan: list[tuple[Path, Path, str]], check: bool) -> list[str]:
    """Copy (or, with check, compare) each (src_file, dest, label) asset. Returns stale labels."""
    stale: list[str] = []
    for src_file, dest, label in plan:
        same = dest.is_file() and filecmp.cmp(src_file, dest, shallow=False)
        rel_dest = dest.relative_to(FORK_ROOT)
        if check:
            print(f"[{'ok' if same else 'STALE'}] {rel_dest}  <-  {label}")
            if not same:
                stale.append(label)
        elif same:
            print(f"[unchanged] {rel_dest}")
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src_file, dest)
            print(f"[vendored]  {rel_dest}  <-  {label}")
    return stale


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--from-release",
        metavar="TAG",
        help="vendor the assets from annotation-ui release TAG (via the `gh` CLI)",
    )
    ap.add_argument(
        "--repo",
        default=DEFAULT_REPO,
        help=f"annotation-ui GitHub repo for --from-release (default: {DEFAULT_REPO})",
    )
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

    if args.from_release:
        return _run_release(
            args.from_release, args.repo, args.check, args.source, args.build
        )
    return _run_source(args.source, args.build, args.check)


def _run_release(
    tag: str, repo: str, check: bool, source: str | None, build: bool
) -> int:
    if build:
        sys.exit("--build has no effect with --from-release (assets are built by CI)")
    if source:
        print(
            "warning: --source is ignored when --from-release is given.",
            file=sys.stderr,
        )

    tmp = download_release(tag, repo)
    try:
        manifest = read_manifest(tmp)
        prov = release_provenance(manifest, tag)

        plan = [(tmp / Path(rel).name, dest, Path(rel).name) for rel, dest in ASSETS]
        missing = [label for src, _, label in plan if not src.is_file()]
        if missing:
            sys.exit(
                f"release {tag!r} is missing asset(s): {', '.join(missing)}. "
                "Was it published by the release-bundles workflow?"
            )

        stale = process_assets(plan, check)

        if check:
            _report_release_provenance(prov)
            if stale:
                print(
                    f"\n{len(stale)} vendored asset(s) differ from release {tag}. Run:\n"
                    f"  python scripts/sync_lcma_assets.py --from-release {tag}\n"
                    "and commit the result.",
                    file=sys.stderr,
                )
                return 1
        else:
            write_release_provenance(prov, PROVENANCE_FILE)
            write_release_provenance(prov, PROVENANCE_FILE_VALIDATOR)
            print(
                f"[provenance] {PROVENANCE_FILE.relative_to(FORK_ROOT)}  ->  "
                f"release {prov['release_tag']} (commit {prov['commit'][:9]})"
            )
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _run_source(source_arg: str | None, build: bool, check: bool) -> int:
    source = resolve_source(source_arg)
    if build:
        run_build(source)

    prov = source_provenance(source)
    if prov["dirty"] == "true" and not check:
        print(
            f"warning: annotation-ui at {source} has uncommitted changes; the vendored bundle "
            f"will not be reproducible from commit {prov['commit'][:9]} alone. Commit the "
            "source first for a clean provenance stamp.",
            file=sys.stderr,
        )

    plan = [(source / rel, dest, rel) for rel, dest in ASSETS]
    missing = [label for src, _, label in plan if not src.is_file()]
    if missing:
        hint = "" if build else " (run with --build, or build the source first)"
        sys.exit(f"source artifact(s) missing: {', '.join(missing)}{hint}")

    stale = process_assets(plan, check)

    if check:
        _report_provenance(prov)
    else:
        write_provenance(prov)
        write_provenance(prov, PROVENANCE_FILE_VALIDATOR)
        flag = "dirty" if prov["dirty"] == "true" else "clean"
        print(
            f"[provenance] {PROVENANCE_FILE.relative_to(FORK_ROOT)}  ->  "
            f"commit {prov['commit'][:9]} ({flag})"
        )

    if check and stale:
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
