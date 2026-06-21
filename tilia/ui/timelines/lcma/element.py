from __future__ import annotations

from tilia.ui.timelines.hierarchy.element import HierarchyUI
from tilia.ui.timelines.lcma.context_menu import LcmaFormContextMenu


class LcmaFormUI(HierarchyUI):
    """UI element for an LCMA form unit.

    Renders exactly like a hierarchy unit for now — the bespoke LCMA render
    contract (zoom-aware attribute display) lands in a later phase. It exists as
    its own class so the ``LCMA_FORM -> element class`` dispatch, the
    LCMA-namespaced context menu, and the builder-dock wiring have a stable home.
    """

    CONTEXT_MENU_CLASS = LcmaFormContextMenu

    def on_select(self) -> None:
        super().on_select()
        # Selecting an LCMA unit opens (creating on first use) the builder dock
        # and loads this unit's annotation. The import is deferred so QtWebEngine
        # is only pulled in when a unit is actually selected — never during plain
        # element creation or in backend-only tests.
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
