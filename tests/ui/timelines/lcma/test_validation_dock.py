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

from tilia.requests import Get, get


def _dock():
    from tilia.ui.timelines.lcma.validation_dock import get_validation_dock_if_exists

    return get_validation_dock_if_exists()


def _feed(dock, diagnostics):
    """Hand the dock the JSON its JS engine would have returned (bypassing the webview)."""
    dock._on_diagnostics(json.dumps(diagnostics))


def _error(index, name=""):
    """A minimal error diagnostic flagging the unit at `index` in the session order."""
    return {
        "index": index,
        "name": name,
        "severity": "error",
        "code": "x",
        "message": "m",
    }


def _row_component_id(item):
    return item.data(0, Qt.ItemDataRole.UserRole)


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


class TestClickScrollsToUnit:
    """todo #4: clicking a finding scrolls the timeline to the flagged unit (centred on its start),
    so the finding you clicked isn't pointing off-screen."""

    def test_clicking_finding_centres_timeline_on_unit_start(
        self, lcma_tlui, lcma_tl, monkeypatch
    ):
        dock = _dock()
        unit = lcma_tl.create_lcma_form(3, 5, 1)[0]  # start = 3
        dock._ordered_ids = [unit.id]
        _feed(dock, [_error(0)])
        calls = []
        monkeypatch.setattr(
            lcma_tlui.collection, "center_on_time", lambda t: calls.append(t)
        )

        dock._on_item_clicked(dock._tree.topLevelItem(0), 0)

        assert calls == [lcma_tlui.get_element(unit.id).get_data("start")]


class TestSelectionMirrorsToRow:
    """todo #3: selecting a unit on the timeline mirror-selects its finding row (the reverse of the
    click path); deselecting clears it; a unit with no finding clears any prior highlight; and a
    recompute that rebuilds the tree keeps the selected unit's row highlighted. Driven end-to-end
    through the element select path (LcmaFormUI.on_select -> dock.highlight_unit)."""

    def test_selecting_unit_selects_its_row(self, lcma_tlui, lcma_tl):
        dock = _dock()
        u0 = lcma_tl.create_lcma_form(0, 1, 1)[0]
        u1 = lcma_tl.create_lcma_form(1, 2, 1)[0]
        dock._ordered_ids = [u0.id, u1.id]  # natural order: level, start
        _feed(dock, [_error(0), _error(1)])

        lcma_tlui.select_element(lcma_tlui.get_element(u1.id))

        current = dock._tree.currentItem()
        assert current is not None
        assert _row_component_id(current) == u1.id

    def test_deselecting_unit_clears_the_row(self, lcma_tlui, lcma_tl):
        dock = _dock()
        u0 = lcma_tl.create_lcma_form(0, 1, 1)[0]
        dock._ordered_ids = [u0.id]
        _feed(dock, [_error(0)])
        ui = lcma_tlui.get_element(u0.id)

        lcma_tlui.select_element(ui)
        assert dock._tree.currentItem() is not None
        lcma_tlui.deselect_element(ui)

        assert dock._tree.currentItem() is None

    def test_selecting_unit_without_finding_clears_prior_highlight(
        self, lcma_tlui, lcma_tl
    ):
        dock = _dock()
        u0 = lcma_tl.create_lcma_form(0, 1, 1)[0]  # flagged
        u1 = lcma_tl.create_lcma_form(1, 2, 1)[0]  # clean, no row
        dock._ordered_ids = [u0.id, u1.id]
        _feed(dock, [_error(0)])

        lcma_tlui.select_element(lcma_tlui.get_element(u0.id))
        assert dock._tree.currentItem() is not None  # u0's row
        lcma_tlui.select_element(lcma_tlui.get_element(u1.id))  # clean unit

        assert dock._tree.currentItem() is None

    def test_recompute_keeps_selected_units_row_highlighted(self, lcma_tlui, lcma_tl):
        dock = _dock()
        u0 = lcma_tl.create_lcma_form(0, 1, 1)[0]
        dock._ordered_ids = [u0.id]
        _feed(dock, [_error(0)])
        lcma_tlui.select_element(lcma_tlui.get_element(u0.id))
        assert _row_component_id(dock._tree.currentItem()) == u0.id

        _feed(
            dock, [_error(0)]
        )  # a recompute rebuilds the tree (clear() drops selection)

        current = dock._tree.currentItem()
        assert current is not None and _row_component_id(current) == u0.id


class TestElementErrorMarkers:
    """The dock mirrors each unit's worst severity onto its element (todo #3): an ERROR flags the
    element so it paints the ⊗ marker, anything else clears it. Here the finding JSON is fed
    directly; the element-side paint is covered in test_element_render.TestValidationErrorMarker.
    """

    @staticmethod
    def _element(dock, cmp_id):
        return get(Get.TIMELINE_UI_ELEMENT, dock._tl_id, cmp_id)

    def test_error_finding_flags_the_units_element(self, lcma_tlui, lcma_tl):
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
        assert self._element(dock, unit.id)._has_validation_error is True

    def test_warning_finding_does_not_flag_the_element(self, lcma_tlui, lcma_tl):
        dock = _dock()
        unit = lcma_tl.create_lcma_form(0, 1, 1)[0]
        dock._ordered_ids = [unit.id]
        _feed(
            dock,
            [
                {
                    "index": 0,
                    "name": "",
                    "severity": "warning",
                    "code": "proposed-term",
                    "message": "m",
                }
            ],
        )
        assert self._element(dock, unit.id)._has_validation_error is False

    def test_marker_clears_on_next_clean_recompute(self, lcma_tlui, lcma_tl):
        dock = _dock()
        unit = lcma_tl.create_lcma_form(0, 1, 1)[0]
        dock._ordered_ids = [unit.id]
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
        assert self._element(dock, unit.id)._has_validation_error is True
        _feed(dock, [])  # the error was resolved
        assert self._element(dock, unit.id)._has_validation_error is False

    def test_only_the_flagged_unit_among_several_is_marked(self, lcma_tlui, lcma_tl):
        dock = _dock()
        u0 = lcma_tl.create_lcma_form(0, 1, 1)[0]
        u1 = lcma_tl.create_lcma_form(1, 2, 1)[0]
        dock._ordered_ids = [u0.id, u1.id]  # natural order: level, start
        _feed(
            dock,
            [
                {
                    "index": 1,
                    "name": "",
                    "severity": "error",
                    "code": "x",
                    "message": "m",
                }
            ],
        )
        assert self._element(dock, u0.id)._has_validation_error is False
        assert self._element(dock, u1.id)._has_validation_error is True


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
