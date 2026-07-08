from __future__ import annotations

from tilia.ui.menus import MenuItemKind
from tilia.ui.timelines.base.context_menus import TimelineUIElementContextMenu

# Mirrors HierarchyContextMenu, but the unit-editing entries point at the
# `timeline.lcma.*` command family (registered by the inherited
# register_commands) rather than `timeline.hierarchy.*` — otherwise a
# right-click on an LCMA unit would dispatch to a hierarchy timeline. The
# `timeline.component.*` / `timeline.element.*` entries are kind-agnostic and
# shared as-is.
DEFAULT_ITEMS = [
    (MenuItemKind.COMMAND, "timeline.element.inspect"),
    (MenuItemKind.SEPARATOR, None),
    (MenuItemKind.COMMAND, "timeline.lcma.increase_level"),
    (MenuItemKind.COMMAND, "timeline.lcma.decrease_level"),
    (MenuItemKind.COMMAND, "timeline.component.set_color"),
    (MenuItemKind.COMMAND, "timeline.component.reset_color"),
    (MenuItemKind.SEPARATOR, None),
    (MenuItemKind.COMMAND, "timeline.component.copy"),
    (MenuItemKind.COMMAND, "timeline.component.paste"),
    (MenuItemKind.COMMAND, "timeline.component.paste_complete"),
    (MenuItemKind.SEPARATOR, None),
    (MenuItemKind.COMMAND, "timeline.component.delete"),
]


class LcmaFormContextMenu(TimelineUIElementContextMenu):
    title = "LCMA form"

    def __init__(self, element):
        self.items = DEFAULT_ITEMS.copy()
        if not element.has_pre_start:
            self.items.insert(6, (MenuItemKind.COMMAND, "timeline.lcma.add_pre_start"))

        if not element.has_post_end:
            self.items.insert(6, (MenuItemKind.COMMAND, "timeline.lcma.add_post_end"))

        super().__init__(element)
