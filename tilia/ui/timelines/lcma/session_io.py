from __future__ import annotations

from tilia.requests import Get, get


def get_session_annotations(timeline_id: int) -> list[tuple[int, str]]:
    """Ordered ``(component_id, annotation_data)`` for every unit on one LCMA timeline.

    ``annotation_data`` is each unit's per-label JSON-LD (the string the builder writes).
    The list *position* is the session index the diagnostics engine reports findings
    against, so the validation dock can map a ``Diagnostic.index`` back to the unit it
    flags. Order is the components' natural order (``ORDERING_ATTRS`` = ``level, start``),
    so it stays stable across recomputes without an explicit sort key.

    Kept free of any Qt / webview dependency (mirrors ``builder_io``) so the session-gathering
    and index mapping stay unit-testable without constructing a QWebEngineView. Returns ``[]``
    when the timeline id is unknown (a stale reference); never raises.
    """
    timeline = get(Get.TIMELINE, timeline_id)
    if timeline is None:
        return []
    return [(unit.id, unit.get_data("annotation_data") or "") for unit in sorted(timeline)]
