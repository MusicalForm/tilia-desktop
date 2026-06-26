from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPen

from tilia.ui.color import get_tinted_color
from tilia.ui.consts import TINT_FACTOR_ON_SELECTION
from tilia.ui.timelines.copy_paste import CopyAttributes
from tilia.ui.timelines.hierarchy.element import (
    HierarchyBody,
    HierarchyLabel,
    HierarchyUI,
)
from tilia.ui.timelines.lcma.context_menu import LcmaFormContextMenu
from tilia.ui.timelines.lcma.span_view import (
    display_label,
    lod_for,
    parse_span_model,
    span_html,
    span_tooltip,
)


class LcmaFormUI(HierarchyUI):
    """UI element for an LCMA form unit.

    Renders the unit's ``annotation_data`` (a JSON-LD label) using the LCMA "zoomed-out"
    render contract (``span_view``): the body fill is the function-family colour, and the
    inline label is the annotation headline (name · function | type · badges) shed by
    level-of-detail as the span narrows. An explicit user colour still wins, and an
    un-annotated unit falls back to a plain hierarchy render.

    The class also owns the ``LCMA_FORM -> element class`` dispatch, the LCMA-namespaced
    context menu, and the builder-dock wiring.
    """

    CONTEXT_MENU_CLASS = LcmaFormContextMenu
    # LCMA units are edited in the builder dock, not the shared Inspector — opt out so selecting
    # a unit doesn't also raise/populate the generic Inspector. The INSPECTOR_FIELD_EDITED route
    # stays live (base.select_element still listens), so the builder dock can drive start/end/
    # comments through the same validated path.
    INSPECTABLE = False
    # The lynchpin for live feedback: a builder-dock save flows
    # set_component_data -> TIMELINE_COMPONENT_SET_DATA_DONE -> element.update(attr, value),
    # which no-ops unless the attr is a trigger. Adding "annotation_data" makes a dock edit
    # repaint the rectangle via update_annotation_data().
    UPDATE_TRIGGERS = HierarchyUI.UPDATE_TRIGGERS + ["annotation_data"]

    # Carry annotation_data through copy/paste. HierarchyUI's copy attrs omit it; the hierarchy
    # copy now reads each element's OWN attrs (get_copy_data_from_hierarchy_ui), and paste skips
    # attrs the target lacks, so an LCMA->hierarchy paste drops it cleanly.
    DEFAULT_COPY_ATTRIBUTES = CopyAttributes(
        values=HierarchyUI.DEFAULT_COPY_ATTRIBUTES.values + ["annotation_data"],
        context=list(HierarchyUI.DEFAULT_COPY_ATTRIBUTES.context),
    )

    # LCMA bands are taller than plain hierarchies: the multi-line annotation label (name,
    # function | type, material, attributes) needs vertical room. These override the (settings-
    # backed) hierarchy heights and are read by LcmaFormBody.get_rect / LcmaFormLabel.get_point
    # below, so the taller bands are confined to LCMA timelines — plain hierarchies are untouched.
    # frame_handle_y already calls self.base_height(), so the frame handles follow automatically.
    # base_height is the level-1 band height — generous so a wrapped level-1 label clears the
    # timeline's bottom edge with a comfortable margin (the label hangs from the band top).
    LCMA_BASE_HEIGHT = 56
    LCMA_LEVEL_HEIGHT_DIFF = 60

    @staticmethod
    def base_height() -> int:
        return LcmaFormUI.LCMA_BASE_HEIGHT

    @staticmethod
    def x_increment_per_lvl() -> int:
        return LcmaFormUI.LCMA_LEVEL_HEIGHT_DIFF

    def __init__(self, *args, **kwargs):
        # Parsed-model cache, keyed on the raw JSON-LD string so we only re-parse on change.
        # Set BEFORE super().__init__ because the base ctor's _setup_label/_setup_body read
        # the span model.
        self._span_model_src: str | None = None
        self._span_model = None
        super().__init__(*args, **kwargs)
        self._update_tooltip()

    # --- annotation -> display model -------------------------------------------

    @property
    def span_model(self):
        """The parsed SpanModel for the current annotation, or None when unannotated."""
        src = self.get_data("annotation_data") or ""
        if src != self._span_model_src:
            self._span_model_src = src
            self._span_model = parse_span_model(src)
        return self._span_model

    def _display_text(self, width: float) -> str:
        """The plain, single-line projection of the annotation at this body width (the abbreviated
        headline + badges), or the raw hierarchy label when there is no annotation. Backs the
        tooltip-adjacent/plain consumers and the render tests; the painted label is the rich
        multi-line HTML from ``_display_html``."""
        model = self.span_model
        if model is None:
            return self.get_data("label")
        return display_label(model, lod_for(width))

    def _display_html(self, width: float) -> str:
        """The rich multi-line HTML label for the current annotation at this body width, or ``""``
        when unannotated (the plain label is painted then). Width drives the LOD tier and, via
        setTextWidth, the wrapping — there is no substring cropping."""
        model = self.span_model
        if model is None:
            return ""
        return span_html(model, lod_for(width))

    @property
    def ui_color(self):
        base_color = self.get_data("color")
        if not base_color:
            model = self.span_model
            base_color = model.color if model else self.level_color
        return (
            base_color
            if not self.is_selected()
            else get_tinted_color(base_color, TINT_FACTOR_ON_SELECTION)
        )

    # --- rendering (override the label to draw the annotation headline) --------

    def _setup_body(self):
        # Same as HierarchyUI._setup_body but with a notional-aware body, so a notional
        # function ("…") draws the dashed border channel from the render contract.
        self.body = LcmaFormBody(
            self.get_data("level"),
            self.start_x,
            self.end_x,
            self.timeline_ui.get_data("height"),
            self.ui_color,
        )
        self.scene.addItem(self.body)
        self._apply_notional_border()

    def _apply_notional_border(self):
        model = self.span_model
        notional = model.flags.notional if model else False
        self.body.set_notional(notional, self.is_selected())

    def _setup_label(self):
        # A wrapping, multi-line rich-text label pinned to the band's top-left (not the centred,
        # substring-cropped HierarchyLabel). It is positioned/filled by _render_label.
        self.label = LcmaFormLabel(
            self.start_x,
            self.timeline_ui.get_data("height"),
            self.get_data("level"),
            "",
        )
        self.scene.addItem(self.label)
        self._render_label(
            self.start_x,
            self.end_x,
            self.get_data("level"),
            self.timeline_ui.get_data("height"),
        )

    def _render_label(self, start_x, end_x, level, height):
        """Paint the label: the rich HTML breakdown when annotated, the plain unit label when not.
        The width (end_x - start_x) drives both the LOD tier and the text-wrapping width."""
        width = end_x - start_x
        model = self.span_model
        if model is None:
            self.label.set_plain(self.get_data("label") or "", width)
        else:
            self.label.set_html(span_html(model, lod_for(width)), width)
        self.label.set_position(start_x, height, level)

    def update_label(self, start_x=None, end_x=None, level=None, height=None):
        start_x = start_x if start_x is not None else self.start_x
        end_x = end_x if end_x is not None else self.end_x
        level = level if level is not None else self.get_data("level")
        height = height if height is not None else self.timeline_ui.get_data("height")
        self._render_label(start_x, end_x, level, height)

    def update_label_position(self, level, height, start_x, end_x):
        # The LCMA label hangs from the band's top-LEFT, so it takes start_x — not the midpoint
        # the centred base label uses. See LcmaFormLabel.get_point.
        self.label.set_position(start_x, height, level)

    def update_annotation_data(self):
        # A builder-dock edit landed. Re-parse and repaint fill, label, border and tooltip.
        self._span_model_src = None
        self.update_color()
        self.update_label()
        self._apply_notional_border()
        self._update_tooltip()

    def _update_tooltip(self):
        model = self.span_model
        tooltip = span_tooltip(model) if model else ""
        self.body.setToolTip(tooltip)
        self.label.setToolTip(tooltip)

    # --- builder-dock wiring ---------------------------------------------------

    def on_select(self) -> None:
        super().on_select()
        # Selecting an LCMA unit opens (creating on first use) the builder dock and loads
        # this unit's annotation. The import is deferred so QtWebEngine is only pulled in
        # when a unit is actually selected — never during plain element creation or in
        # backend-only tests.
        from tilia.ui.timelines.lcma.builder_dock import get_or_create_builder_dock

        dock = get_or_create_builder_dock()
        dock.load_annotation(
            self.timeline_ui.id, self.id, self.get_data("annotation_data")
        )

    def on_deselect(self) -> None:
        super().on_deselect()
        from tilia.ui.timelines.lcma.builder_dock import get_builder_dock_if_exists

        dock = get_builder_dock_if_exists()
        if dock is not None:
            dock.clear_annotation(self.id)


class LcmaFormBody(HierarchyBody):
    """A hierarchy body that draws a dashed border when its unit's function is *notional*
    (the render contract's ``.is-notional`` channel — a function the analyst marks as implied,
    not literally present). Selection still shows the solid pen; on deselect the body returns
    to the dashed border instead of no border, so the channel survives select/deselect.
    """

    def __init__(self, *args, **kwargs):
        # Must exist before super().__init__, which calls set_pen_style_no_pen().
        self.notional = False
        super().__init__(*args, **kwargs)

    def set_notional(self, notional: bool, selected: bool) -> None:
        self.notional = notional
        # Don't disturb the solid selection pen; the dashed border is (re)applied on deselect
        # via HierarchyBody.on_deselect -> set_pen_style_no_pen.
        if not selected:
            self.set_pen_style_no_pen()

    def set_pen_style_no_pen(self):
        # "no border" becomes "dashed border" for a notional unit.
        if self.notional:
            pen = QPen(QColor("black"))
            pen.setStyle(Qt.PenStyle.DashLine)
            self.setPen(pen)
        else:
            super().set_pen_style_no_pen()

    @staticmethod
    def get_rect(level: int, start_x: float, end_x: float, tl_height: float):
        # Same geometry as HierarchyBody.get_rect, but with the taller LCMA band heights so a band
        # grows to fit the multi-line label. HierarchyBody.get_rect reads HierarchyUI's heights
        # directly (not via self), so it cannot pick up the LcmaFormUI overrides — hence this.
        x0 = start_x + HierarchyUI.X_OFFSET
        y0 = (
            tl_height
            - HierarchyUI.Y_OFFSET
            - (
                LcmaFormUI.base_height()
                + ((level - 1) * LcmaFormUI.x_increment_per_lvl())
            )
        )
        x1 = end_x - HierarchyUI.X_OFFSET
        y1 = tl_height - HierarchyUI.Y_OFFSET
        return QRectF(QPointF(x0, y0), QPointF(x1, y1))


class LcmaFormLabel(HierarchyLabel):
    """A hierarchy label that renders the LCMA span as wrapped, multi-line rich text pinned to the
    band's top-left, instead of a single centred, substring-cropped line. ``set_html`` paints the
    rich breakdown (span_view.span_html); ``set_plain`` is the unannotated fallback (the raw unit
    label). Positioning uses the taller LCMA band heights, so it sits at the band's top.
    """

    LEFT_PAD = 4
    TOP_PAD = 2

    def set_html(self, html_text: str, width: float):
        # setTextWidth makes the rich text WRAP to the body width (minus padding); the label sheds
        # lines by LOD rather than being substring-cropped. Skip a no-op repaint (drag fires this
        # often) when neither the HTML nor the wrap width changed.
        text_width = max(width - 2 * self.LEFT_PAD, 0.0)
        if html_text == getattr(self, "_html", None) and text_width == self.textWidth():
            return
        self._html = html_text
        self.setTextWidth(text_width)
        self.setHtml(html_text)

    def set_plain(self, text: str, width: float):
        self._html = None
        self.setTextWidth(max(width - 2 * self.LEFT_PAD, 0.0))
        self.set_text(text)

    def get_point(self, x: float, tl_height, level):
        # x is the band's LEFT edge (LcmaFormUI passes start_x), not the centre the base uses; the
        # label hangs from the band's top-left with a small pad, using the LCMA band heights.
        y = (
            tl_height
            - HierarchyUI.Y_OFFSET
            - (
                LcmaFormUI.base_height()
                + ((level - 1) * LcmaFormUI.x_increment_per_lvl())
            )
        )
        return QPointF(x + self.LEFT_PAD, y + self.TOP_PAD)
