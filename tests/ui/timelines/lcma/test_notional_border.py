"""LCMA form bodies always carry a resting contour so adjacent pale family-tint spans stay
separable. A *notional* function ("…", an implied-not-literal function) upgrades that contour to
a dashed body border — the render contract's .is-notional channel. Both must survive the LOD crop
(they are borders, not text) and the select/deselect pen swap (selection shows the solid black
pen, deselect returns to the contour / dashed border).
"""

import json

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from tilia.ui.timelines.lcma.element import LcmaFormBody


def _is_resting_contour(body: LcmaFormBody) -> bool:
    """The deselected, non-notional resting stroke: a thin muted contour (distinct from the black
    selection pen, which is also solid)."""
    pen = body.pen()
    return (
        pen.style() == Qt.PenStyle.SolidLine
        and pen.color() == QColor(LcmaFormBody.CONTOUR_COLOR)
        and pen.width() == LcmaFormBody.CONTOUR_WIDTH
    )


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


def test_unannotated_unit_shows_the_resting_contour(lcma_form_ui):
    assert _is_resting_contour(lcma_form_ui.body)


def test_notional_unit_draws_a_dashed_border(lcma_form_ui):
    lcma_form_ui.set_data("annotation_data", _jsonld(notional=True))
    assert lcma_form_ui.body.pen().style() == Qt.PenStyle.DashLine


def test_non_notional_unit_shows_the_resting_contour(lcma_form_ui):
    lcma_form_ui.set_data("annotation_data", _jsonld(notional=False))
    assert _is_resting_contour(lcma_form_ui.body)


def test_border_reverts_to_contour_when_annotation_is_removed(lcma_form_ui):
    lcma_form_ui.set_data("annotation_data", _jsonld(notional=True))
    assert lcma_form_ui.body.pen().style() == Qt.PenStyle.DashLine
    lcma_form_ui.set_data("annotation_data", "")
    assert _is_resting_contour(lcma_form_ui.body)


def test_selection_pen_wins_then_reverts_to_dashed_on_deselect(lcma_form_ui):
    lcma_form_ui.set_data("annotation_data", _jsonld(notional=True))
    # drive the body's selection pen directly (avoids the builder-dock side effects of the
    # element's on_select)
    lcma_form_ui.body.on_select()
    assert lcma_form_ui.body.pen().style() == Qt.PenStyle.SolidLine
    assert lcma_form_ui.body.pen().color() == QColor("black")
    lcma_form_ui.body.on_deselect()
    assert lcma_form_ui.body.pen().style() == Qt.PenStyle.DashLine


def test_non_notional_selection_reverts_to_contour_on_deselect(lcma_form_ui):
    lcma_form_ui.set_data("annotation_data", _jsonld(notional=False))
    lcma_form_ui.body.on_select()
    assert lcma_form_ui.body.pen().style() == Qt.PenStyle.SolidLine
    assert lcma_form_ui.body.pen().color() == QColor("black")
    lcma_form_ui.body.on_deselect()
    assert _is_resting_contour(lcma_form_ui.body)
