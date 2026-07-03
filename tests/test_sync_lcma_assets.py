"""Unit tests for the provenance helpers in scripts/sync_lcma_assets.py.

The script is not importable as a package module (it lives in scripts/), so load it by path.
These cover only the git-provenance stamping — the copy/build flow needs a real annotation-ui
checkout and is exercised by hand + the vendored-asset guard in
tests/ui/timelines/lcma/test_vendored_assets.py.
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "sync_lcma_assets.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("sync_lcma_assets", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *args],
        check=True,
        capture_output=True,
    )


def _init_repo(path: Path) -> Path:
    path.mkdir()
    _git(path, "init", "-q")
    (path / "f.txt").write_text("hi")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "init")
    return path


@pytest.fixture
def mod():
    return _load_script()


class TestSourceProvenance:
    def test_clean_repo_reports_full_sha_and_not_dirty(self, mod, tmp_path):
        repo = _init_repo(tmp_path / "src")
        prov = mod.source_provenance(repo)
        assert len(prov["commit"]) == 40
        assert prov["dirty"] == "false"
        assert prov["branch"]  # some branch name

    def test_uncommitted_change_marks_dirty(self, mod, tmp_path):
        repo = _init_repo(tmp_path / "src")
        (repo / "f.txt").write_text("changed")  # tracked file, uncommitted
        assert mod.source_provenance(repo)["dirty"] == "true"

    def test_untracked_file_marks_dirty(self, mod, tmp_path):
        repo = _init_repo(tmp_path / "src")
        (repo / "new.txt").write_text("x")  # untracked
        assert mod.source_provenance(repo)["dirty"] == "true"

    def test_non_git_dir_is_unknown(self, mod, tmp_path):
        prov = mod.source_provenance(tmp_path)  # no .git here
        assert prov["commit"] == "unknown"
        assert prov["dirty"] == "unknown"

    def test_detached_head_labels_branch(self, mod, tmp_path):
        repo = _init_repo(tmp_path / "src")
        _git(repo, "checkout", "-q", "--detach", "HEAD")
        prov = mod.source_provenance(repo)
        assert prov["branch"] == "(detached)"  # not the raw "HEAD"
        assert prov["dirty"] == "false"
        assert len(prov["commit"]) == 40


class TestProvenanceRoundTrip:
    def test_write_then_read(self, mod, tmp_path):
        dest = tmp_path / "SOURCE.txt"
        prov = {"commit": "a" * 40, "branch": "feat/x", "dirty": "false"}
        mod.write_provenance(prov, dest)
        back = mod.read_provenance(dest)
        assert back["commit"] == "a" * 40
        assert back["branch"] == "feat/x"
        assert back["dirty"] == "false"

    def test_header_present_and_comments_ignored(self, mod, tmp_path):
        dest = tmp_path / "SOURCE.txt"
        mod.write_provenance({"commit": "abc", "branch": "b", "dirty": "true"}, dest)
        text = dest.read_text()
        assert text.startswith("# Provenance")
        # comment lines starting with '#' must not leak into the parsed mapping
        assert "#" not in mod.read_provenance(dest)

    def test_read_missing_file_is_empty(self, mod, tmp_path):
        assert mod.read_provenance(tmp_path / "nope.txt") == {}
