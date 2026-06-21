from tilia.ui.timelines.toolbar import TimelineToolbar


class LcmaTimelineToolbar(TimelineToolbar):
    """Mirrors HierarchyTimelineToolbar but fires the ``timeline.lcma.*`` command family
    (registered by the inherited register_commands), so the buttons act on the LCMA timeline
    rather than a hierarchy one. The commands reuse the hierarchy icons/handlers."""

    COMMANDS = [
        "timeline.lcma.split",
        "timeline.lcma.merge",
        "timeline.lcma.group",
        "timeline.lcma.increase_level",
        "timeline.lcma.decrease_level",
        "timeline.lcma.create_child",
    ]
