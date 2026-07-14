"""Live, in-app webview test for the LCMA validation dock's headless diagnostics engine.

Boots the real app fixtures and the eager-created LcmaValidationDock (an invisible QWebEnginePage
loading the vendored validator.html), then drives it through the Qt event loop to prove, end to end
and inside TiLiA, that:

  * validator.html loads under file:// and window.diagnoseSession is defined (_engine_ready)
  * diagnoseSession runs in the page and returns valid JSON for an empty session ("[]")
  * a real recompute over units with a duplicate name flows session_io -> the live engine ->
    _render, listing the duplicate-name findings natively

This is the piece the mocked unit tests (test_validation_dock.py) can't cover: that a viewless
QWebEnginePage actually executes the vendored JS. Opt-in (LCMA_LIVE=1) to keep the normal suite
fast and non-flaky."""

import json
import os

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

pytestmark = pytest.mark.skipif(
    os.environ.get("LCMA_LIVE") != "1",
    reason="live webview test; set LCMA_LIVE=1 to run",
)


def _dock():
    from tilia.ui.timelines.lcma.validation_dock import get_validation_dock_if_exists

    return get_validation_dock_if_exists()


def _wait_until(predicate, timeout_ms=20000, step_ms=50) -> bool:
    waited = 0
    while waited < timeout_ms:
        if predicate():
            return True
        QTest.qWait(step_ms)
        waited += step_ms
    return predicate()


def _read_js(dock, js, timeout_ms=5000):
    result = {}
    dock._page.runJavaScript(js, lambda r: result.__setitem__("v", r))
    _wait_until(lambda: "v" in result, timeout_ms)
    return result.get("v")


def _finding_texts(dock):
    tree = dock._tree
    return [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]


def test_engine_boots_and_diagnoses_empty(lcma_tl, lcma_tlui):
    dock = _dock()
    assert dock is not None
    assert _wait_until(
        lambda: dock._engine_ready
    ), "validator.html never finished loading"
    # diagnoseSession runs in the viewless page and returns valid JSON (empty session -> "[]").
    assert _read_js(dock, "diagnoseSession([])") == "[]"


def test_recompute_runs_live_engine_and_lists_findings(lcma_tl, lcma_tlui):
    dock = _dock()
    assert _wait_until(lambda: dock._engine_ready)
    label = json.dumps({"name": "x", "forms": []})
    # Two non-overlapping units sharing a name -> duplicate-name errors (name-based, so their
    # spans only need to differ enough to coexist on the timeline).
    for start, end in ((0, 1), (1, 2)):
        unit = lcma_tl.create_lcma_form(start, end, 1)[0]
        lcma_tl.set_component_data(unit.id, "annotation_data", label)

    dock._recompute()  # real runJavaScript -> real diagnoseSession -> _render (async)

    assert _wait_until(
        lambda: dock._tree.topLevelItemCount() >= 1
        and "clean" not in dock._summary.text()
    ), f"live engine produced no findings (summary={dock._summary.text()!r})"
    assert "error" in dock._summary.text().lower()
    QApplication.instance().processEvents()


def test_unknown_committed_term_flagged_as_error(lcma_tl, lcma_tlui):
    """A committed function outside the vocabulary — not authorable in the builder, only reachable by
    an external .tla edit — is flagged as an error by the live engine. Minimal JSON-LD: revLabel reads
    the compact form the app controls, so the full @context is not needed to drive the rule.
    """
    dock = _dock()
    assert _wait_until(lambda: dock._engine_ready)
    unknown = json.dumps(
        {
            "@type": ["lcma:AnnotationLabel"],
            "name": "u",
            "forms": [
                {
                    "@type": "lcma:Form",
                    "function": {"@type": "lcma:Function", "hasCategory": "fn:wubwub"},
                }
            ],
        }
    )
    unit = lcma_tl.create_lcma_form(0, 1, 1)[0]
    lcma_tl.set_component_data(unit.id, "annotation_data", unknown)

    dock._recompute()

    assert _wait_until(
        lambda: any("controlled vocabulary" in t for t in _finding_texts(dock))
    ), f"unknown committed term not flagged (findings={_finding_texts(dock)!r})"
    assert "error" in dock._summary.text().lower()
    QApplication.instance().processEvents()


def test_unreadable_unit_does_not_blind_the_pane(lcma_tl, lcma_tlui):
    """A unit whose annotation_data is not parseable JSON — a broken external edit — is flagged as a
    single `unreadable` error, not a whole-session engine failure that leaves the pane blank.
    """
    dock = _dock()
    assert _wait_until(lambda: dock._engine_ready)
    bad = lcma_tl.create_lcma_form(0, 1, 1)[0]
    lcma_tl.set_component_data(bad.id, "annotation_data", "{ this is not valid json")

    dock._recompute()

    assert _wait_until(
        lambda: any("Unreadable" in t for t in _finding_texts(dock))
    ), f"malformed unit not flagged as unreadable (findings={_finding_texts(dock)!r})"
    assert "error" in dock._summary.text().lower()
    QApplication.instance().processEvents()
