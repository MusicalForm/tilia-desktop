"""A notional function ("…", an implied-not-literal function) draws a dashed body border —
the render contract's .is-notional channel. It must survive the LOD crop (it is a border, not
text) and the select/deselect pen swap (selection shows the solid pen, deselect returns to the
dashed border).
"""

import json

from PySide6.QtCore import Qt

from tilia.ui.timelines.lcma.element import LcmaFormBody


def _jsonld(notional: bool):
    return json.dumps(
        {
            "forms": [
                {
                    "@type": "lcma:Form",
                    "function": {"hasCategory": "fn:basic_idea", "notional": notional},
                }
            ]
        }
    )


def test_element_uses_the_notional_aware_body(lcma_form_ui):
    assert isinstance(lcma_form_ui.body, LcmaFormBody)


def test_unannotated_unit_has_no_border(lcma_form_ui):
    assert lcma_form_ui.body.pen().style() == Qt.PenStyle.NoPen


def test_notional_unit_draws_a_dashed_border(lcma_form_ui):
    lcma_form_ui.set_data("annotation_data", _jsonld(notional=True))
    assert lcma_form_ui.body.pen().style() == Qt.PenStyle.DashLine


def test_non_notional_unit_has_no_border(lcma_form_ui):
    lcma_form_ui.set_data("annotation_data", _jsonld(notional=False))
    assert lcma_form_ui.body.pen().style() == Qt.PenStyle.NoPen


def test_border_clears_when_annotation_is_removed(lcma_form_ui):
    lcma_form_ui.set_data("annotation_data", _jsonld(notional=True))
    assert lcma_form_ui.body.pen().style() == Qt.PenStyle.DashLine
    lcma_form_ui.set_data("annotation_data", "")
    assert lcma_form_ui.body.pen().style() == Qt.PenStyle.NoPen


def test_selection_pen_wins_then_reverts_to_dashed_on_deselect(lcma_form_ui):
    lcma_form_ui.set_data("annotation_data", _jsonld(notional=True))
    # drive the body's selection pen directly (avoids the builder-dock side effects of the
    # element's on_select)
    lcma_form_ui.body.on_select()
    assert lcma_form_ui.body.pen().style() == Qt.PenStyle.SolidLine
    lcma_form_ui.body.on_deselect()
    assert lcma_form_ui.body.pen().style() == Qt.PenStyle.DashLine
