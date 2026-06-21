"""LcmaFormUI render tests: the annotation drives the rectangle (family fill + headline +
tooltip), and a builder-dock-style edit live-repaints it (the UPDATE_TRIGGERS lynchpin).

These exercise the real update path: ``element.set_data("annotation_data", ...)`` flows
through set_component_data -> TIMELINE_COMPONENT_SET_DATA_DONE -> element.update(), exactly
as a save from the builder dock does.
"""

import json

from PySide6.QtGui import QColor

from tilia.ui.timelines.lcma import span_view as sv


def _jsonld(name="Theme A", category="fn:basic_idea", main_type="type:period"):
    form = {"@type": "lcma:Form", "function": {"hasCategory": category}}
    if main_type:
        form["formalType"] = {"@type": "lcma:FormalType", "hasCategory": main_type}
    return json.dumps({"name": name, "forms": [form]})


def _name(color: str) -> str:
    return QColor(color).name()


class TestUnannotated:
    def test_falls_back_to_plain_hierarchy(self, lcma_form_ui):
        # A fresh unit has no annotation: no span model, plain (level) colour, raw label.
        el = lcma_form_ui
        assert el.span_model is None
        assert _name(el.body.brush().color().name()) == _name(el.level_color)
        el.set_data("label", "raw")
        assert el._display_text(250) == "raw"


class TestAnnotatedRender:
    def test_body_fill_is_family_colour(self, lcma_form_ui):
        el = lcma_form_ui
        el.set_data("annotation_data", _jsonld())
        assert el.span_model is not None
        assert _name(el.body.brush().color().name()) == _name(
            sv.span_color_hex("Basic idea")
        )

    def test_label_shows_headline_at_full_width(self, lcma_form_ui):
        el = lcma_form_ui
        el.set_data("annotation_data", _jsonld())
        # px width is view-dependent; assert the composed text directly at a full tier.
        text = el._display_text(250)
        assert "Theme A" in text and "Basic idea" in text and "Period" in text

    def test_tooltip_is_set_from_annotation(self, lcma_form_ui):
        el = lcma_form_ui
        el.set_data("annotation_data", _jsonld())
        assert "Theme A" in el.body.toolTip()
        assert "Theme A" in el.label.toolTip()

    def test_user_colour_overrides_family(self, lcma_form_ui):
        el = lcma_form_ui
        el.set_data("annotation_data", _jsonld())
        el.set_data("color", "#123456")
        assert _name(el.body.brush().color().name()) == _name("#123456")


class TestLiveRepaintLynchpin:
    def test_annotation_data_is_an_update_trigger(self, lcma_form_ui):
        assert "annotation_data" in type(lcma_form_ui).UPDATE_TRIGGERS

    def test_edit_repaints_fill_label_and_tooltip(self, lcma_form_ui):
        el = lcma_form_ui
        # connective amber -> closing red: a single edit must move every channel.
        el.set_data("annotation_data", _jsonld(name="Br", category="fn:transition"))
        assert _name(el.body.brush().color().name()) == _name(
            sv.span_color_hex("Transition")
        )
        assert "Transition" in el._display_text(250)
        assert "Br" in el.body.toolTip()

        el.set_data("annotation_data", _jsonld(name="Cad", category="fn:cadence"))
        assert _name(el.body.brush().color().name()) == _name(
            sv.span_color_hex("Cadence")
        )
        assert "Cadence" in el._display_text(250)
        assert "Cad" in el.body.toolTip()

    def test_clearing_annotation_reverts_to_plain(self, lcma_form_ui):
        el = lcma_form_ui
        el.set_data("annotation_data", _jsonld())
        el.set_data("annotation_data", "")
        assert el.span_model is None
        assert _name(el.body.brush().color().name()) == _name(el.level_color)
