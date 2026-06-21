from __future__ import annotations

from tilia.timelines.base.timeline import TimelineFlag
from tilia.timelines.component_kinds import ComponentKind
from tilia.timelines.hierarchy.timeline import HierarchyTimeline
from tilia.timelines.lcma.components import LcmaForm


class LcmaTimeline(HierarchyTimeline):
    """A Hierarchy timeline whose units are LCMA form annotations.

    Reuses all of :class:`HierarchyTimeline`'s nested-unit machinery — it was
    parameterized over ``COMPONENT_KIND`` / ``COMPONENT_CLASS`` for exactly
    this. The only differences are:

    * the component kind/class point at :class:`LcmaForm`, and
    * the ``COMPONENTS_IMPORTABLE`` flag is dropped — there is no CSV importer
      for LCMA forms (annotations come from the embedded builder, not a
      spreadsheet), and keeping the flag would auto-register a
      ``timelines.import.lcma`` command with no parser behind it.

    Discovery is convention-based: this subclass is found by
    ``Timeline.subclasses()`` (now a recursive descent) and its ``type_name()``
    resolves to ``"Lcma"`` for the add-timeline command and ``.tla``
    serialization.
    """

    COMPONENT_KIND = ComponentKind.LCMA_FORM
    COMPONENT_CLASS = LcmaForm
    FLAGS = [
        TimelineFlag.COMPONENTS_COLORED,
        TimelineFlag.COMPONENTS_COPYABLE,
    ]
