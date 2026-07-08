"""Guard the vendored LCMA web assets (embed.html + validator.html + vocab.json).

These files are copied in from the annotation-ui repo by scripts/sync_lcma_assets.py and are
easy to vendor wrong (empty write, truncated bundle, stale path). A bad embed.html means a blank
builder dock; a bad validator.html means a dead validation pane; a bad vocab.json means headlines
silently fall back to un-abbreviated terms.
These run inside the fork's own suite (no cross-repo dependency), so a botched re-vendor fails
CI here rather than at runtime on a user's machine.
"""

import json
from pathlib import Path

import pytest

import tilia.ui.timelines.lcma.span_view as sv

LCMA_DIR = Path(sv.__file__).resolve().parent
EMBED_HTML = LCMA_DIR / "builder" / "embed.html"
VALIDATOR_HTML = LCMA_DIR / "validator" / "validator.html"
# LCMA_DIR parents: [0] timelines, [1] ui, [2] tilia, [3] repo root
REPO_ROOT = LCMA_DIR.parents[3]


class TestVendoredEmbed:
    def test_present_and_substantial(self):
        assert EMBED_HTML.is_file(), f"missing vendored builder: {EMBED_HTML}"
        # the single-file bundle inlines all JS+CSS; it is ~330KB. A few KB means a broken or
        # non-inlined build was vendored.
        assert EMBED_HTML.stat().st_size > 50_000

    def test_has_bridge_and_loader_markers(self):
        html = EMBED_HTML.read_text(encoding="utf-8")
        assert "loadAnnotation" in html  # Python -> JS entry point (embed.tsx)
        # Bridge markers that survive minification (the literal "qwebchannel" identifier does not):
        # the Qt transport the channel hooks, and the JS -> Py save slot from the contract.
        assert "webChannelTransport" in html  # QWebChannel transport hook
        assert "save_annotation" in html  # JS -> Py slot (LcmaBuilderBackend)
        assert "LCMA Annotation Builder" in html  # the embed entry's <title>


class TestVendoredValidator:
    def test_present_and_substantial(self):
        assert VALIDATOR_HTML.is_file(), f"missing vendored validator: {VALIDATOR_HTML}"
        # single-file bundle inlining the diagnose() engine + jsonld parser (~20KB, no React). A
        # few hundred bytes means a broken or non-inlined build was vendored.
        assert VALIDATOR_HTML.stat().st_size > 10_000

    def test_exposes_diagnose_session_and_inlines_engine(self):
        html = VALIDATOR_HTML.read_text(encoding="utf-8")
        assert "diagnoseSession" in html  # the Py -> JS entry the validation dock calls (validator.ts)
        # a diagnostic message string only present if the engine (model/diagnostics.ts) inlined
        assert "Undefined reference" in html


class TestVendoredVocab:
    def test_present_and_parses(self):
        assert sv._VOCAB_PATH.is_file(), f"missing vendored vocab: {sv._VOCAB_PATH}"
        data = json.loads(sv._VOCAB_PATH.read_text(encoding="utf-8"))
        assert isinstance(data, dict)
        assert data["functions"]["specific"]  # non-empty
        assert all("name" in e and "abbr" in e for e in data["functions"]["specific"])
        assert data["types"]["main"]

    def test_span_view_loaded_nonempty_maps_consistent_with_file(self):
        # the maps span_view built at import must be non-empty and reflect the vendored file,
        # otherwise headlines would silently degrade to the prettified full term
        assert sv.FUNCTION_ABBR, "FUNCTION_ABBR empty — vocab.json failed to load"
        assert sv.MAIN_TYPE_ABBR
        data = json.loads(sv._VOCAB_PATH.read_text(encoding="utf-8"))
        first_type = data["types"]["main"][0]
        assert sv.MAIN_TYPE_ABBR[first_type["name"]] == first_type["abbr"]
        first_fn = data["functions"]["specific"][0]
        assert sv.FUNCTION_ABBR[first_fn["name"]] == first_fn["abbr"]


class TestPackagingDeclaresAssets:
    """The frozen (Nuitka) build bundles a file only if it is in pyproject's
    [tool.setuptools.package-data] (scripts/deploy.py._update_yml turns those patterns into
    Nuitka data-files). If either asset is dropped from package-data, the desktop build ships a
    blank dock / un-abbreviated headlines — so guard the declaration here."""

    def _package_data(self):
        try:
            import tomllib
        except ModuleNotFoundError:  # py < 3.11
            pytest.skip("tomllib unavailable")
        data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        return data["tool"]["setuptools"]["package-data"]["tilia"]

    def test_lcma_web_assets_are_declared(self):
        pkg = self._package_data()
        assert "ui/timelines/lcma/builder/embed.html" in pkg
        assert "ui/timelines/lcma/validator/validator.html" in pkg
        assert "ui/timelines/lcma/vocab.json" in pkg
