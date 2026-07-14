"""Live, in-app webview test for the LCMA builder dock.

Boots the real app fixtures, constructs the actual LcmaBuilderDock (a real
QWebEngineView loading the vendored embed.html), and drives it through the Qt
event loop to prove, end to end and inside TiLiA:

  * the builder boots under file:// and the QWebChannel handshake fires
    (backend.ready) -> _bridge_ready
  * a COMMITTED edit in the builder (type a function, then ⌘⏎) calls
    backend.save_annotation, which writes JSON-LD onto the real LCMA component
    via set_component_data (JS -> Py). The editor is the AttributeEntry bar now,
    and it saves DISCRETELY on ⌘⏎ — not live per keystroke.
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

# The bar renders committed slots as chips (text) and keeps drafts in inputs, so read BOTH the
# visible text and every input value, lowercased — robust to the bar's exact DOM.
READ_STATE = (
    "(function () {"
    "  var vals = [].slice.call(document.querySelectorAll('input'))"
    "    .map(function (i) { return i.value; });"
    "  var text = document.body ? document.body.innerText : '';"
    "  return (text + '|' + vals.join('|')).toLowerCase();"
    "})()"
)


def _commit_function_js(value: str) -> str:
    # Type `value` into the bar's first input (the function slot) and commit with ⌘⏎ / Ctrl+⏎,
    # which the bar routes to onUpdate -> backend.save_annotation. Stands in for a user edit; the
    # bar no longer saves on the input event alone (the form-based live-save editor is retired).
    return (
        "(function () {"
        f"  var v = {json.dumps(value)};"
        "  var input = document.querySelector('input');"
        "  if (!input) return 'no-input';"
        "  var setter = Object.getOwnPropertyDescriptor("
        "    window.HTMLInputElement.prototype, 'value').set;"
        "  setter.call(input, v);"
        "  input.dispatchEvent(new Event('input', { bubbles: true }));"
        "  input.dispatchEvent(new KeyboardEvent('keydown',"
        "    { key: 'Enter', metaKey: true, ctrlKey: true, bubbles: true }));"
        "  return 'ok';"
        "})()"
    )


def _walk_function_js(value: str) -> str:
    # Like _commit_function_js but a PLAIN Enter (no ⌘/Ctrl): the analyst WALKS OFF the function slot
    # rather than force-committing. advance() folds the buffer in and persists the draft live
    # (onLiveEdit -> backend.save_annotation) — the sticky-editor path TiLiA's analysts actually use,
    # and the one auto-naming has to ride too (they don't press ⌘⏎).
    return (
        "(function () {"
        f"  var v = {json.dumps(value)};"
        "  var input = document.querySelector('input');"
        "  if (!input) return 'no-input';"
        "  var setter = Object.getOwnPropertyDescriptor("
        "    window.HTMLInputElement.prototype, 'value').set;"
        "  setter.call(input, v);"
        "  input.dispatchEvent(new Event('input', { bubbles: true }));"
        "  input.dispatchEvent(new KeyboardEvent('keydown',"
        "    { key: 'Enter', bubbles: true }));"
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

        # 2. JS -> Py: a ⌘⏎ commit writes JSON-LD (with the committed function) onto the component
        _run_js(dock, _commit_function_js("verse"))
        assert _wait_until(
            lambda: "verse" in (lcma_form.annotation_data or "")
        ), f"save_annotation did not reach the component: {lcma_form.annotation_data!r}"

        # 3. Py -> JS: pushing a distinct annotation back shows it in the bar
        chorus = json.dumps(
            {
                "forms": [
                    {
                        "@type": "lcma:Form",
                        "function": {
                            "@type": "lcma:Function",
                            "hasCategory": "fn:chorus",
                        },
                    }
                ]
            }
        )
        dock.load_annotation(lcma_tl.id, lcma_form.id, chorus)
        assert _wait_until(lambda: "chorus" in (_read_js(dock, READ_STATE) or "")), (
            "loadAnnotation did not restore the builder "
            f"(got {_read_js(dock, READ_STATE)!r})"
        )
    finally:
        dock.deleteLater()
        QApplication.instance().processEvents()


def test_session_units_drive_autoname_increment(lcma_tl, lcma_form, lcma_tlui):
    """End-to-end proof of the auto-name numbering fix: the OTHER units' names, pushed over the
    channel (setSessionUnits) by load_annotation, reach the embed and make autoName number a
    fresh unit v -> v2. This is the seam that was broken (the embed hardcoded an empty unit list),
    so a real webview is exercised, not a mocked one.
    """
    from tilia.ui.timelines.lcma.builder_dock import LcmaBuilderDock

    dock = LcmaBuilderDock()
    try:
        assert _wait_until(lambda: dock._bridge_ready), "bridge never became ready"

        # Unit A: bind it, then commit a blank-named verse. No sibling names yet, so autoName gives
        # the bare abbreviation -> @id anno:v.
        dock.load_annotation(lcma_tl.id, lcma_form.id, "")
        QTest.qWait(400)
        _run_js(dock, _commit_function_js("verse"))
        assert _wait_until(lambda: '"anno:v"' in (lcma_form.annotation_data or "")), (
            "unit A was not auto-named the bare 'v': " f"{lcma_form.annotation_data!r}"
        )

        # Unit B: binding it pushes A's committed JSON-LD to the embed (load_annotation ->
        # _push_session_units -> setSessionUnits), so the embed now knows the name 'v' is taken.
        b = lcma_tl.create_lcma_form(2, 3, 1)[0]
        dock.load_annotation(lcma_tl.id, b.id, "")
        QTest.qWait(
            600
        )  # let setSessionUnits + the embed's React state settle before committing

        # B is a verse too, blank-named -> autoName must number it around A's 'v' -> 'v2'.
        _run_js(dock, _commit_function_js("verse"))
        assert _wait_until(lambda: "v2" in (b.annotation_data or "")), (
            "unit B was not auto-incremented to 'v2' (setSessionUnits did not reach autoName): "
            f"{b.annotation_data!r}"
        )
    finally:
        dock.deleteLater()
        QApplication.instance().processEvents()


def test_walk_off_autonames(lcma_tl, lcma_form, lcma_tlui):
    """Auto-naming must ride the LIVE-persist path, not just ⌘⏎. The embed is a sticky live-save
    editor (builder_dock): walking off a slot with a PLAIN ⏎ (or Tab / blur) persists the unit
    without a ⌘⏎ — the way analysts actually commit. So a blank-named verse walked off must be
    auto-named the bare 'v', and a second one must number to 'v2', exactly as ⌘⏎ does.
    """
    from tilia.ui.timelines.lcma.builder_dock import LcmaBuilderDock

    dock = LcmaBuilderDock()
    try:
        assert _wait_until(lambda: dock._bridge_ready), "bridge never became ready"

        # Unit A: bind, type a verse, WALK the slot (plain ⏎, no meta). The live persist must
        # auto-name it -> @id anno:v, without any ⌘⏎.
        dock.load_annotation(lcma_tl.id, lcma_form.id, "")
        QTest.qWait(400)
        _run_js(dock, _walk_function_js("verse"))
        assert _wait_until(lambda: '"anno:v"' in (lcma_form.annotation_data or "")), (
            "walking off a verse did not auto-name it 'v' (live-save skipped autoName): "
            f"{lcma_form.annotation_data!r}"
        )

        # Unit B: binding pushes A's committed name over setSessionUnits; walking off B's verse must
        # number it v2, proving the session count reaches the live path too.
        b = lcma_tl.create_lcma_form(2, 3, 1)[0]
        dock.load_annotation(lcma_tl.id, b.id, "")
        QTest.qWait(600)
        _run_js(dock, _walk_function_js("verse"))
        assert _wait_until(lambda: "v2" in (b.annotation_data or "")), (
            "walking off a second verse did not auto-increment to 'v2': "
            f"{b.annotation_data!r}"
        )
    finally:
        dock.deleteLater()
        QApplication.instance().processEvents()
