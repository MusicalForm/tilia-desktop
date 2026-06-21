"""Live, in-app webview test for the LCMA builder dock.

Boots the real app fixtures, constructs the actual LcmaBuilderDock (a real
QWebEngineView loading the vendored embed.html), and drives it through the Qt
event loop to prove, end to end and inside TiLiA:

  * the builder boots under file:// and the QWebChannel handshake fires
    (backend.ready) -> _bridge_ready
  * a simulated edit in the builder calls backend.save_annotation, which writes
    JSON-LD onto the real LCMA component via set_component_data (JS -> Py)
  * pushing a previously-saved annotation back via loadAnnotation restores it in
    the builder (Py -> JS)

It spins a real web-engine event loop, so it is opt-in (set LCMA_LIVE=1) to keep
the normal suite fast and non-flaky. The plain unit tests in test_builder.py
cover the Python logic without a webview.
"""

import json
import os

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

pytestmark = pytest.mark.skipif(
    os.environ.get("LCMA_LIVE") != "1",
    reason="live webview test; set LCMA_LIVE=1 to run",
)

READ_NAME = (
    "document.querySelector('.name-row input') ? "
    "document.querySelector('.name-row input').value : '<no-input>'"
)


def _set_name_js(value: str) -> str:
    # Drive the builder's controlled name input via React's native value setter
    # + an input event, as a stand-in for a user edit (this is what fires
    # save_annotation). Mirrors the annotation-ui embed spike.
    return (
        "(function () {"
        f"  var v = {json.dumps(value)};"
        "  var input = document.querySelector('.name-row input');"
        "  if (!input) return 'no-input';"
        "  var setter = Object.getOwnPropertyDescriptor("
        "    window.HTMLInputElement.prototype, 'value').set;"
        "  setter.call(input, v);"
        "  input.dispatchEvent(new Event('input', { bubbles: true }));"
        "  return 'ok';"
        "})()"
    )


def _wait_until(predicate, timeout_ms=20000, step_ms=50) -> bool:
    waited = 0
    while waited < timeout_ms:
        if predicate():
            return True
        QTest.qWait(step_ms)
        waited += step_ms
    return predicate()


def _run_js(dock, js, settle_ms=400) -> None:
    dock.view.page().runJavaScript(js)
    QTest.qWait(settle_ms)
    QApplication.instance().processEvents()


def _read_js(dock, js, timeout_ms=5000):
    result = {}
    dock.view.page().runJavaScript(js, lambda r: result.__setitem__("v", r))
    _wait_until(lambda: "v" in result, timeout_ms)
    return result.get("v")


def test_dock_boots_and_round_trips(lcma_tl, lcma_form, lcma_tlui):
    from tilia.ui.timelines.lcma.builder_dock import LcmaBuilderDock

    dock = LcmaBuilderDock()
    try:
        # 1. webview boots + channel connects
        assert _wait_until(
            lambda: dock._bridge_ready
        ), "QWebChannel bridge never became ready (backend.ready not called)"

        dock.load_annotation(lcma_tl.id, lcma_form.id, lcma_form.annotation_data or "")

        # 2. JS -> Py: a builder edit writes JSON-LD onto the real component
        _run_js(dock, _set_name_js("LiveEdit"))
        assert _wait_until(
            lambda: "LiveEdit" in (lcma_form.annotation_data or "")
        ), f"save_annotation did not reach the component: {lcma_form.annotation_data!r}"
        saved_live = lcma_form.annotation_data

        # change it again so the next step is a visible restore
        _run_js(dock, _set_name_js("Changed"))
        assert _wait_until(lambda: "Changed" in (lcma_form.annotation_data or ""))

        # 3. Py -> JS: pushing the earlier annotation back restores it in the UI
        dock.load_annotation(lcma_tl.id, lcma_form.id, saved_live)
        assert _wait_until(lambda: _read_js(dock, READ_NAME) == "LiveEdit"), (
            "loadAnnotation did not restore the builder's name field "
            f"(got {_read_js(dock, READ_NAME)!r})"
        )
    finally:
        dock.deleteLater()
        QApplication.instance().processEvents()
