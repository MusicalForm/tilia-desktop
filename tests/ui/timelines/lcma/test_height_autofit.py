"""Todo 13: an LCMA band grown past the timeline's height — by grouping, or by raising a unit's
level — must make the timeline auto-grow so the tall band's top stays on-screen.

LCMA bands are far taller than plain hierarchy bands (LcmaFormUI overrides base_height /
x_increment_per_lvl to 56 / 60, against the hierarchy 25 / 25). The auto-fit lives in
HierarchyTimelineUI.get_max_hierarchy_height, but it used to measure with the *base* hierarchy
constants, so on an LCMA timeline it under-measured the needed height and the tallest band
clipped off the top. It now measures with the timeline's own element class.

These drive the real user paths (the ``timeline.lcma.*`` group / increase_level commands) and
assert the tallest band's top edge — via the same ``LcmaFormBody.get_rect`` the paint uses —
sits on-screen (y >= 0).
"""

from tilia.ui import commands
from tilia.ui.timelines.lcma.element import LcmaFormBody


def _tallest_band_top(tlui) -> float:
    """The y (from the timeline's top) of the highest band's top edge, computed with the real
    paint geometry. Negative means the band clips off the top of the timeline."""
    max_level = max(
        tlui.timeline.component_manager.get_existing_values_for_attr(
            "level", tlui.timeline.COMPONENT_KIND
        )
    )
    rect = LcmaFormBody.get_rect(max_level, 0.0, 100.0, tlui.get_data("height"))
    return rect.top()


class TestHeightAutofit:
    def test_default_height_clips_a_level_3_band(self, lcma_tlui):
        # Guard the premise: at the default height an LCMA level-3 band does NOT fit, so the
        # auto-fit below is doing real work rather than passing vacuously.
        rect = LcmaFormBody.get_rect(3, 0.0, 100.0, lcma_tlui.get_data("height"))
        assert rect.top() < 0

    def test_raising_a_unit_into_a_tall_band_grows_the_timeline(self, lcma_tlui):
        tl = lcma_tlui
        tl.create_lcma_form(0, 1, 1)
        el = next(iter(tl))

        # Ctrl+Up twice: level 1 -> 3. A level-3 LCMA band is taller than the default timeline.
        tl.select_element(el)
        commands.execute("timeline.lcma.increase_level")
        tl.select_element(el)
        commands.execute("timeline.lcma.increase_level")

        assert el.get_data("level") == 3
        assert _tallest_band_top(tl) >= 0

    def test_grouping_into_a_tall_band_grows_the_timeline(self, lcma_tlui):
        # The reported repro: nested grouping to level 3. Group the two left leaves, then group
        # that level-2 parent with the right leaf -> a level-3 grandparent.
        tl = lcma_tlui
        for start in (0, 1, 2):
            tl.create_lcma_form(start, start + 1, 1)
        leaves = sorted(tl, key=lambda e: e.get_data("start"))

        tl.select_element(leaves[0])
        tl.select_element(leaves[1])
        commands.execute("timeline.lcma.group")
        tl.deselect_all_elements()

        parent = next(e for e in tl if e.get_data("level") == 2)
        right_leaf = next(
            e for e in tl if e.get_data("level") == 1 and e.get_data("start") == 2
        )
        tl.select_element(parent)
        tl.select_element(right_leaf)
        commands.execute("timeline.lcma.group")

        assert max(e.get_data("level") for e in tl) == 3
        assert _tallest_band_top(tl) >= 0
