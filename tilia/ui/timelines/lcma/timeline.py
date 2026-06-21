from __future__ import annotations

from tilia.timelines.lcma.timeline import LcmaTimeline
from tilia.ui.timelines.hierarchy.timeline import HierarchyTimelineUI
from tilia.ui.timelines.lcma.element import LcmaFormUI


class LcmaTimelineUI(HierarchyTimelineUI):
    """UI for an LCMA form timeline.

    Inherits hierarchy editing wholesale (create-child / group / split / merge,
    drag, arrow-key navigation). ``register_commands`` is inherited unchanged:
    because it namespaces commands by ``timeline_class.type_name()``, invoking
    it for this class registers a distinct ``timeline.lcma.*`` family wired to
    the same handlers — no clash with ``timeline.hierarchy.*``. Shared single-key
    shortcuts (s / g / e / c) are disambiguated by the last-clicked timeline
    kind.

    Toolbar and dynamic menu are left off for now (set to ``None`` so the
    Hierarchy ones — whose buttons fire ``timeline.hierarchy.*`` — are not
    inherited). Editing is available via keyboard shortcuts and the
    LCMA context menu; the dedicated toolbar and the builder dock arrive in the
    next phase.
    """

    ELEMENT_CLASS = LcmaFormUI
    timeline_class = LcmaTimeline
    TOOLBAR_CLASS = None
    menu_class = None
