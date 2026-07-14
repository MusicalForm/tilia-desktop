"""LcmaFormUI render tests: the annotation drives the rectangle (level fill + headline +
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
    def test_empty_unit_renders_as_empty_lcma_form(self, lcma_form_ui):
        # A fresh unit has no annotation, but it still renders as an (empty) LCMA form — the "—"
        # em-dash placeholder headline — not a blank band (todo #2). The fill is the level colour
        # (like every LCMA unit since todo #1); the empty state reads from the label, not the fill.
        el = lcma_form_ui
        assert (
            el.span_model is not None
        )  # placeholder model, not the None (malformed) fallback
        assert el._display_text(250) == "—"  # em-dash headline
        assert _name(el.body.brush().color().name()) == _name(
            el.level_color
        )  # level fill
        assert el.body.toolTip() == ""  # nothing annotated yet -> no tooltip

    def test_empty_unit_ignores_a_stale_label(self, lcma_form_ui):
        # A label attr lingering on the unit must not resurface: an un-annotated LCMA unit shows
        # the empty-form placeholder, never the raw label.
        el = lcma_form_ui
        el.set_data("label", "raw")
        assert el._display_text(250) == "—"


class TestEmptyUnitFormatting:
    """todo #2: an un-annotated LCMA unit — the initial unit of a fresh timeline, or either half of
    splitting an empty unit — renders as an empty LCMA form (the "—" placeholder headline), not a
    blank band. The fill stays the level colour (todo #1). Regression guard for the reported bug."""

    def _is_empty_form(self, el) -> bool:
        return el._display_text(250) == "—" and _name(
            el.body.brush().color().name()
        ) == _name(el.level_color)

    def test_initial_unit_of_fresh_timeline_is_an_empty_lcma_form(self, tls, tluis):
        # The exact repro: a brand-new LCMA timeline's auto-created unit must show the "—" headline,
        # not paint as a blank band.
        from tilia.timelines.lcma.timeline import LcmaTimeline

        tl = tls.create_timeline(LcmaTimeline)  # keeps the auto-created initial unit
        tlui = tluis.get_timeline_ui(tl.id)
        el = tlui.get_element(next(iter(tl)).id)
        assert self._is_empty_form(el)

    def test_splitting_an_empty_unit_leaves_both_halves_empty_forms(
        self, lcma_tlui, lcma_tl
    ):
        # Splitting the un-annotated unit keeps both halves empty LCMA forms ("—"), not blank bands.
        lcma_tl.create_lcma_form(0, 10, 1)
        lcma_tl.split(5)
        assert len(lcma_tl) == 2
        for comp in lcma_tl:
            assert self._is_empty_form(lcma_tlui.get_element(comp.id))


class TestAnnotatedRender:
    def test_body_fill_is_level_colour(self, lcma_form_ui):
        # The annotation drives the headline, but the FILL is the band's level colour, not the
        # function family (todo #1): an annotated unit matches a plain one at the same level.
        el = lcma_form_ui
        el.set_data("annotation_data", _jsonld())
        assert el.span_model is not None
        assert _name(el.body.brush().color().name()) == _name(el.level_color)

    def test_label_shows_headline_at_full_width(self, lcma_form_ui):
        el = lcma_form_ui
        el.set_data("annotation_data", _jsonld())
        # px width is view-dependent; assert the composed text directly at a full tier.
        text = el._display_text(250)
        assert "Theme A" in text  # name
        assert sv.FUNCTION_ABBR["basic_idea"] in text  # abbreviated function
        assert sv.MAIN_TYPE_ABBR["period"] in text  # abbreviated type

    def test_painted_label_is_the_rich_html_label(self, lcma_form_ui):
        from tilia.ui.timelines.lcma.element import LcmaFormLabel

        assert isinstance(lcma_form_ui.label, LcmaFormLabel)

    def test_html_label_shows_full_names_at_full_width(self, lcma_form_ui):
        # The reported bug: a wide unit showed only the abbreviated "fn | type" (e.g. "Core | caaba").
        # The painted label is now rich HTML with the FULL names at full width.
        el = lcma_form_ui
        el.set_data("annotation_data", _jsonld())
        html = el._display_html(250)
        assert "Theme A" in html  # name line
        assert "Basic idea" in html  # full function name (not "bi")
        assert "Period" in html  # full type name (not "pd")
        # painting at a wide width drives the rich HTML onto the label (HTML -> plain text),
        # proving _render_label is wired through to span_html
        el.update_label(0, 300)
        assert "Basic idea" in el.label.toPlainText()

    def test_multi_operand_headline_sheds_lod_earlier(self, lcma_form_ui):
        # A 3-operand transformation headline is ~3× as wide, so the element picks its LOD tier
        # against width/units. At 130px a plain function still shows full names ('med'/'full'), but
        # the transformation sheds to the abbreviated 'short' tier instead of overflowing the band.
        el = lcma_form_ui
        transformation = json.dumps(
            {
                "forms": [
                    {
                        "@type": "lcma:Form",
                        "function": {
                            "@type": "lcma:FunctionOperation",
                            "operator": "fnop:transformation",
                            "operands": [
                                {"hasCategory": "fn:basic_idea"},
                                {"hasCategory": "fn:cadence"},
                                {"hasCategory": "fn:transition"},
                            ],
                        },
                    }
                ]
            }
        )
        el.set_data("annotation_data", transformation)
        assert el.span_model.headline_units == 3
        # 130px -> 130/3 ≈ 43 -> 'short' (abbreviated); without the units divisor this would be
        # 'med' and paint the full names.
        assert "Basic idea" not in el._display_html(130)
        # given enough width (500/3 ≈ 166 -> 'full') the full names return
        assert "Basic idea" in el._display_html(500)
        # a plain function at the same 130px keeps its full-name label (ladder unchanged)
        el.set_data("annotation_data", _jsonld())
        assert "Basic idea" in el._display_html(130)

    def test_tooltip_is_set_from_annotation(self, lcma_form_ui):
        el = lcma_form_ui
        el.set_data("annotation_data", _jsonld())
        assert "Theme A" in el.body.toolTip()
        assert "Theme A" in el.label.toolTip()

    def test_user_colour_overrides_level(self, lcma_form_ui):
        el = lcma_form_ui
        el.set_data("annotation_data", _jsonld())
        el.set_data("color", "#123456")
        assert _name(el.body.brush().color().name()) == _name("#123456")


class TestLiveRepaintLynchpin:
    def test_annotation_data_is_an_update_trigger(self, lcma_form_ui):
        assert "annotation_data" in type(lcma_form_ui).UPDATE_TRIGGERS

    def test_edit_repaints_fill_label_and_tooltip(self, lcma_form_ui):
        el = lcma_form_ui
        # A single edit must move every annotation channel (headline + tooltip). The FILL stays
        # the band's level colour regardless of function (todo #1), so it does not track the edit.
        el.set_data("annotation_data", _jsonld(name="Br", category="fn:transition"))
        assert _name(el.body.brush().color().name()) == _name(el.level_color)
        assert sv.FUNCTION_ABBR["transition"] in el._display_text(250)
        assert "Br" in el.body.toolTip()  # name + full term live in the tooltip
        assert "Transition" in el.body.toolTip()

        el.set_data("annotation_data", _jsonld(name="Cad", category="fn:cadence"))
        assert _name(el.body.brush().color().name()) == _name(el.level_color)
        assert sv.FUNCTION_ABBR["cadence"] in el._display_text(250)
        assert "Cad" in el.body.toolTip()
        assert "Cadence" in el.body.toolTip()

    def test_clearing_annotation_reverts_to_empty_form(self, lcma_form_ui):
        el = lcma_form_ui
        el.set_data("annotation_data", _jsonld())
        el.set_data("annotation_data", "")
        assert el.span_model is not None  # back to the empty-form placeholder
        assert el._display_text(250) == "—"  # "—" headline, not a blank label
        assert _name(el.body.brush().color().name()) == _name(el.level_color)
        assert el.body.toolTip() == ""  # tooltip cleared with the annotation


# The ⊗ error marker (todo #3): the validation dock calls set_validation_error() after its session
# lint; the element paints a leading ⊗ over the headline. Diagnose-driven, so these drive it
# directly (the dock-> element propagation is covered in test_validation_dock.py). ⊗ = U+2297.
_MARK = "⊗"


class TestValidationErrorMarker:
    def test_flagged_annotated_unit_shows_marker(self, lcma_form_ui):
        el = lcma_form_ui
        el.set_data("annotation_data", _jsonld())
        assert _MARK not in el._display_html(250)  # clean by default

        el.set_validation_error(True)
        html = el._display_html(250)
        assert _MARK in html  # leading marker
        assert "Theme A" in html  # ... and the headline still renders
        # the marker reaches the painted label, not just the projection accessor
        el.update_label(0, 300)
        assert _MARK in el.label.toPlainText()

    def test_marker_clears_when_error_resolves(self, lcma_form_ui):
        el = lcma_form_ui
        el.set_data("annotation_data", _jsonld())
        el.set_validation_error(True)
        assert _MARK in el._display_html(250)

        el.set_validation_error(False)
        assert _MARK not in el._display_html(250)

    def test_marker_hidden_at_min_lod_when_unit_too_small(self, lcma_form_ui):
        # The marker rides with the label and sheds once the unit is too small to show any label at
        # all ('min' LOD, width < 32) — it must not linger on a unit that shows nothing else.
        el = lcma_form_ui
        el.set_data("annotation_data", _jsonld())
        el.set_validation_error(True)
        assert _MARK not in el._display_html(10)  # min LOD: marker gone
        assert el._display_html(10) == ""  # ... nothing paints at all
        # still shown while the unit is wide enough to carry a label ('short' and up)
        assert _MARK in el._display_html(40)
        assert _MARK in el._display_html(250)

    def test_flagged_unreadable_unit_shows_marker_over_raw_label(self, lcma_form_ui):
        # An externally-edited unit whose annotation_data is malformed JSON: no span model, so it
        # renders the plain hierarchy label — but the ⊗ must still surface the error.
        el = lcma_form_ui
        el.set_data("label", "raw")
        el.set_data("annotation_data", "{ this is not valid json")
        assert el.span_model is None  # unreadable -> plain fallback

        el.set_validation_error(True)
        html = el._display_html(250)
        assert _MARK in html
        assert "raw" in html  # the raw label is preserved alongside the marker
        el.update_label(0, 300)
        assert _MARK in el.label.toPlainText()

    def test_unreadable_marker_hidden_at_min_lod(self, lcma_form_ui):
        # The shed applies to the unreadable path too: a too-small unreadable unit falls back to its
        # plain label with no marker, like any other too-small unit.
        el = lcma_form_ui
        el.set_data("label", "raw")
        el.set_data("annotation_data", "{ this is not valid json")
        el.set_validation_error(True)
        assert _MARK not in el._display_html(10)  # min LOD: no marker
        el.update_label(0, 10)
        assert _MARK not in el.label.toPlainText()

    def test_unflagged_unreadable_unit_is_plain_without_marker(self, lcma_form_ui):
        el = lcma_form_ui
        el.set_data("label", "raw")
        el.set_data("annotation_data", "{ this is not valid json")
        assert (
            el._display_html(250) == ""
        )  # no error -> plain label path, no HTML marker
        el.update_label(0, 300)
        assert _MARK not in el.label.toPlainText()

    def test_repaint_skipped_when_flag_unchanged(self, lcma_form_ui, monkeypatch):
        el = lcma_form_ui
        el.set_data("annotation_data", _jsonld())
        el.set_validation_error(True)
        calls = []
        monkeypatch.setattr(el, "update_label", lambda *a, **k: calls.append(True))
        el.set_validation_error(True)  # no change -> no repaint
        assert calls == []
        el.set_validation_error(False)  # change -> repaint
        assert calls == [True]
