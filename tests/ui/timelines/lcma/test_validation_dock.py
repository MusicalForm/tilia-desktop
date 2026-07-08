"""Native behaviour of the LCMA validation dock: rendering diagnostics, the clean state, click ->
select, and refresh filtering.

The diagnostics ENGINE is JS (validator.html) and is covered by the annotation-ui suite +
test_vendored_assets. Here the runJavaScript boundary is stubbed so the native tree / index-mapping
/ selection logic is tested deterministically without the live webview. Whether diagnoseSession
actually runs inside the QWebEnginePage is a live/manual concern, like test_dock_live.

The dock is eager-created by the lcma_tlui fixture (LcmaTimelineUI.__init__), bound to that
timeline — the tests fetch that instance rather than constructing their own.
"""

import json

from PySide6.QtCore import Qt


def _dock():
    from tilia.ui.timelines.lcma.validation_dock import get_validation_dock_if_exists

    return get_validation_dock_if_exists()


def _feed(dock, diagnostics):
    """Hand the dock the JSON its JS engine would have returned (bypassing the webview)."""
    dock._on_diagnostics(json.dumps(diagnostics))


class _FakePage:
    """Stand-in for the headless QWebEnginePage: runJavaScript returns a canned result at once."""

    def __init__(self, result: str):
        self._result = result
        self.last_js = None

    def runJavaScript(self, js, callback):
        self.last_js = js
        callback(self._result)


class TestRenderDiagnostics:
    def test_clean_state(self, lcma_tlui):
        dock = _dock()
        _feed(dock, [])
        assert dock._summary.text() == "Validation: clean"
        assert dock._tree.topLevelItemCount() == 1
        hint = dock._tree.topLevelItem(0)
        assert "No reference or vocabulary problems." in hint.text(0)
        assert not (
            hint.flags() & Qt.ItemFlag.ItemIsSelectable
        )  # non-clickable reassurance row

    def test_lists_errors_then_warnings_with_counts(self, lcma_tlui):
        dock = _dock()
        _feed(
            dock,
            [
                {
                    "index": 0,
                    "name": "A",
                    "severity": "error",
                    "code": "undefined-ref",
                    "message": "Undefined reference “Z”.",
                },
                {
                    "index": 1,
                    "name": "B",
                    "severity": "warning",
                    "code": "proposed-term",
                    "message": "Proposed term x.",
                },
            ],
        )
        assert dock._summary.text() == "Validation: 1 error, 1 warning"
        assert dock._tree.topLevelItemCount() == 2
        first = dock._tree.topLevelItem(0).text(0)
        assert "#1 A" in first and "Undefined reference" in first
        assert "#2 B" in dock._tree.topLevelItem(1).text(0)


class TestRecompute:
    def test_gathers_session_calls_engine_and_renders(self, lcma_tlui, lcma_tl):
        dock = _dock()
        dock._engine_ready = True
        unit = lcma_tl.create_lcma_form(0, 1, 1)[0]
        lcma_tl.set_component_data(unit.id, "annotation_data", '{"name":"A"}')
        dock._page = _FakePage(
            json.dumps(
                [
                    {
                        "index": 0,
                        "name": "A",
                        "severity": "error",
                        "code": "x",
                        "message": "m",
                    }
                ]
            )
        )

        dock._recompute()

        assert dock._ordered_ids == [
            unit.id
        ]  # index -> unit mapping built from the session
        assert dock._page.last_js.startswith("diagnoseSession(")
        assert dock._tree.topLevelItemCount() == 1


class TestClickSelectsUnit:
    def test_clicking_finding_selects_the_flagged_unit(self, lcma_tlui, lcma_tl):
        dock = _dock()
        unit = lcma_tl.create_lcma_form(0, 1, 1)[0]
        dock._ordered_ids = [unit.id]  # as a recompute would have set
        _feed(
            dock,
            [
                {
                    "index": 0,
                    "name": "",
                    "severity": "error",
                    "code": "x",
                    "message": "m",
                }
            ],
        )

        dock._on_item_clicked(dock._tree.topLevelItem(0), 0)

        assert unit.id in [el.id for el in lcma_tlui.selected_elements]


class TestRefreshFilter:
    def test_edit_on_bound_timeline_schedules_recompute_others_ignored(
        self, lcma_tlui, monkeypatch
    ):
        dock = _dock()
        calls = []
        monkeypatch.setattr(dock, "_schedule_recompute", lambda: calls.append(True))
        dock._on_component_set_data_done(dock._tl_id, 123)  # bound timeline
        dock._on_component_set_data_done(
            "other-timeline-id", 123
        )  # a different timeline
        assert calls == [True]

    def test_create_delete_on_bound_timeline_schedules_recompute_others_ignored(
        self, lcma_tlui, monkeypatch
    ):
        dock = _dock()
        calls = []
        monkeypatch.setattr(dock, "_schedule_recompute", lambda: calls.append(True))
        dock._on_component_added_or_removed(object, dock._tl_id, "kind")  # bound
        dock._on_component_added_or_removed(
            object, "other-timeline-id", "kind"
        )  # different
        assert calls == [True]
