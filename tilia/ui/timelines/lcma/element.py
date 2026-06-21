from __future__ import annotations

from tilia.ui.color import get_tinted_color
from tilia.ui.consts import TINT_FACTOR_ON_SELECTION
from tilia.ui.timelines.copy_paste import CopyAttributes
from tilia.ui.timelines.hierarchy.element import HierarchyLabel, HierarchyUI
from tilia.ui.timelines.lcma.context_menu import LcmaFormContextMenu
from tilia.ui.timelines.lcma.span_view import (
    display_label,
    lod_for,
    parse_span_model,
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
        """The inline label text for the current annotation at this body width, or the plain
        hierarchy label when there is no annotation yet."""
        model = self.span_model
        if model is None:
            return self.get_data("label")
        return display_label(model, lod_for(width))

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

    def _setup_label(self):
        text = self._display_text(self.end_x - self.start_x)
        self.update_label_substrings_widths(text)
        self.label = HierarchyLabel(
            (self.start_x + self.end_x) / 2,
            self.timeline_ui.get_data("height"),
            self.get_data("level"),
            self.get_cropped_label(self.start_x, self.end_x, text),
        )
        self.scene.addItem(self.label)

    def update_label(self, start_x=None, end_x=None, level=None, height=None):
        start_x = start_x or self.start_x
        end_x = end_x or self.end_x
        level = level or self.get_data("level")
        height = height or self.timeline_ui.get_data("height")

        # The displayed text depends on width (the LOD tier), so recompute it — and its
        # substring widths — whenever it changes, not only when the raw field changes.
        text = self._display_text(end_x - start_x)
        if text != self.label.toPlainText():
            self.update_label_substrings_widths(text)

        self.label.set_text(self.get_cropped_label(start_x, end_x, text))
        self.update_label_position(level, height, start_x, end_x)

    def update_annotation_data(self):
        # A builder-dock edit landed. Re-parse and repaint fill, label and tooltip.
        self._span_model_src = None
        self.update_color()
        self.update_label()
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
