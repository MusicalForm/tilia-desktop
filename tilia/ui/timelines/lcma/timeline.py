from __future__ import annotations

from tilia.timelines.lcma.timeline import LcmaTimeline
from tilia.ui.timelines.hierarchy.timeline import HierarchyTimelineUI
from tilia.ui.timelines.lcma.element import LcmaFormUI
from tilia.ui.timelines.lcma.toolbar import LcmaTimelineToolbar


class LcmaTimelineUI(HierarchyTimelineUI):
    """UI for an LCMA form timeline.

    Inherits hierarchy editing wholesale (create-child / group / split / merge,
    drag, arrow-key navigation). ``register_commands`` is inherited unchanged:
    because it namespaces commands by ``timeline_class.type_name()``, invoking
    it for this class registers a distinct ``timeline.lcma.*`` family wired to
    the same handlers — no clash with ``timeline.hierarchy.*``. Shared single-key
    shortcuts (s / g / e / c) are disambiguated by the last-clicked timeline
    kind.

    The toolbar (``LcmaTimelineToolbar``) fires that ``timeline.lcma.*`` family,
    so its buttons act on this kind. ``menu_class`` stays ``None``: the Hierarchy
    menu only offers CSV import, which LCMA does not support (annotations come
    from the embedded builder); the "Add LCMA" entry lives in the Add menu.
    """

    ELEMENT_CLASS = LcmaFormUI
    timeline_class = LcmaTimeline
    TOOLBAR_CLASS = LcmaTimelineToolbar
    menu_class = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The builder dock is always visible whenever an LCMA timeline exists — not only after a
        # unit is selected. Creating it here (get-or-create is a singleton, so multiple LCMA
        # timelines share the one dock) shows the empty pane up front; selecting a unit then binds
        # it. The import is deferred so QtWebEngine is pulled in only when an LCMA timeline UI is
        # actually built — never during backend-only element creation or backend tests.
        from tilia.ui.timelines.lcma.builder_dock import get_or_create_builder_dock

        get_or_create_builder_dock().show()
