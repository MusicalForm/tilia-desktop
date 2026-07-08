"""The LCMA kind reuses HierarchyTimelineUI.register_commands, which is kind-aware
(register_timeline_command builds ``timeline.{type_name}.{name}``). So an LCMA timeline must
get its own ``timeline.lcma.*`` command family — the context menu points at it, and the shared
single-key shortcuts (c/g/e/s) resolve to it for the focused kind. If registration regressed,
right-click entries and shortcuts would silently dispatch to a hierarchy timeline (or nothing).
"""

import pytest

from tilia.ui import commands
from tilia.ui.menus import MenuItemKind
from tilia.ui.timelines.lcma.context_menu import LcmaFormContextMenu
from tilia.ui.timelines.lcma.toolbar import LcmaTimelineToolbar

# Every hierarchy command, re-namespaced for LCMA. The menu uses the level/frame ones; the
# shortcuts use create_child/group/merge/split — all must exist for the kind.
LCMA_KIND_COMMANDS = [
    "timeline.lcma.increase_level",
    "timeline.lcma.decrease_level",
    "timeline.lcma.add_pre_start",
    "timeline.lcma.add_post_end",
    "timeline.lcma.create_child",
    "timeline.lcma.group",
    "timeline.lcma.merge",
    "timeline.lcma.split",
]


@pytest.mark.usefixtures("lcma_tlui")
class TestLcmaCommands:
    def test_kind_namespaced_commands_are_registered(self):
        for name in LCMA_KIND_COMMANDS:
            commands.get_qaction(name)  # raises ValueError if not registered

    def test_context_menu_references_only_registered_commands(self, lcma_form_ui):
        menu = LcmaFormContextMenu(lcma_form_ui)
        referenced = [
            payload for kind, payload in menu.items if kind == MenuItemKind.COMMAND
        ]
        # the element has neither pre-start nor post-end yet, so both frame commands appear
        assert "timeline.lcma.add_pre_start" in referenced
        assert "timeline.lcma.add_post_end" in referenced
        for name in referenced:
            commands.get_qaction(name)

    def test_no_hierarchy_namespaced_command_leaks_into_the_menu(self, lcma_form_ui):
        # a stray timeline.hierarchy.* entry would dispatch to the wrong kind
        referenced = [
            payload
            for kind, payload in LcmaFormContextMenu(lcma_form_ui).items
            if kind == MenuItemKind.COMMAND
        ]
        assert not any(name.startswith("timeline.hierarchy.") for name in referenced)

    def test_add_menu_entry_uses_the_lcma_acronym(self):
        # type_name() capitalised would read "Lcma"; ADD_MENU_TEXT overrides it to "&LCMA"
        assert commands.get_qaction("timelines.add.lcma").text() == "&LCMA"

    def test_toolbar_builds_and_is_lcma_namespaced(self):
        assert all(c.startswith("timeline.lcma.") for c in LcmaTimelineToolbar.COMMANDS)
        # instantiation calls get_qaction per command -> raises if any is unregistered
        toolbar = LcmaTimelineToolbar()
        assert len(toolbar.actions()) == len(LcmaTimelineToolbar.COMMANDS)
