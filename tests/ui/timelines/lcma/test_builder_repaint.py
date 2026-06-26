"""The builder SAVE path must repaint the on-timeline element, not just write the model.

Covers the reported bug: editing a unit in the embed did not update the label shown in TiLiA.
Two levels:
  * builder_io.set_annotation_data  -> element repaints   (the model->UI half)
  * dock.on_save_annotation         -> component + element (the full dock half, incl. the echo
                                        guard that discrete ⌘⏎ saves rely on)
The live end-to-end (real webview ⌘⏎ -> element) lives in test_dock_live.py.
"""

import json

from tilia.ui.timelines.lcma import builder_io
from tilia.ui.timelines.lcma import span_view as sv


def _jsonld(name, category):
    return json.dumps(
        {
            "name": name,
            "forms": [{"@type": "lcma:Form", "function": {"hasCategory": category}}],
        }
    )


class TestBuilderIoRepaintsElement:
    def test_save_repaints_label_and_tooltip(self, lcma_tl, lcma_tlui, lcma_form):
        el = lcma_tlui.get_element(lcma_form.id)

        builder_io.set_annotation_data(
            lcma_tl.id, lcma_form.id, _jsonld("Aaa", "fn:verse")
        )
        assert "Aaa" in el.body.toolTip()
        assert sv.FUNCTION_ABBR["verse"] in el._display_text(250)

        # a SECOND committed edit must move the rendered channels (not stay stale)
        builder_io.set_annotation_data(
            lcma_tl.id, lcma_form.id, _jsonld("Bbb", "fn:chorus")
        )
        assert "Bbb" in el.body.toolTip()
        assert "Aaa" not in el.body.toolTip()
        assert sv.FUNCTION_ABBR["chorus"] in el._display_text(250)


class TestDockSaveRepaintsElement:
    """Drive the dock's save callback (what backend.save_annotation calls) without a webview, by
    constructing the dock and invoking its bridge callbacks directly."""

    def _dock(self):
        from tilia.ui.timelines.lcma.builder_dock import LcmaBuilderDock

        return LcmaBuilderDock()

    def test_on_save_annotation_writes_and_repaints(
        self, lcma_tl, lcma_tlui, lcma_form
    ):
        el = lcma_tlui.get_element(lcma_form.id)
        dock = self._dock()
        try:
            dock.load_annotation(lcma_tl.id, lcma_form.id, "")
            dock.on_save_annotation(_jsonld("Solo", "fn:solo"))
            assert "Solo" in (lcma_form.annotation_data or "")
            assert "Solo" in el.body.toolTip()
            assert sv.FUNCTION_ABBR["solo"] in el._display_text(250)
        finally:
            dock.deleteLater()

    def test_unchanged_commit_is_dropped_by_echo_guard(
        self, lcma_tl, lcma_tlui, lcma_form
    ):
        el = lcma_tlui.get_element(lcma_form.id)
        dock = self._dock()
        try:
            value = _jsonld("Verse", "fn:verse")
            dock.load_annotation(lcma_tl.id, lcma_form.id, value)  # _last_value = value
            # committing the same value again must NOT write (no spurious undo / no-op repaint)
            dock.on_save_annotation(value)
            assert (lcma_form.annotation_data or "") == ""  # nothing written
            # a real change DOES write + repaint
            dock.on_save_annotation(_jsonld("Verse", "fn:chorus"))
            assert sv.FUNCTION_ABBR["chorus"] in el._display_text(250)
        finally:
            dock.deleteLater()
