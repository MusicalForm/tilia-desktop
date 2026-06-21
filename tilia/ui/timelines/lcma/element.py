from __future__ import annotations

from tilia.ui.timelines.hierarchy.element import HierarchyUI
from tilia.ui.timelines.lcma.context_menu import LcmaFormContextMenu


class LcmaFormUI(HierarchyUI):
    """UI element for an LCMA form unit.

    Renders exactly like a hierarchy unit for now — the bespoke LCMA render
    contract (zoom-aware attribute display) lands in a later phase. It exists as
    its own class so the ``LCMA_FORM -> element class`` dispatch, the
    LCMA-namespaced context menu, and future LCMA-specific painting have a
    stable home.
    """

    CONTEXT_MENU_CLASS = LcmaFormContextMenu
