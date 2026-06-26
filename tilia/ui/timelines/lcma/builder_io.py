from __future__ import annotations

from tilia.requests import Get, Post, get, post


def set_annotation_data(timeline_id: int, component_id: int, jsonld: str) -> bool:
    """Persist the builder's JSON-LD onto an LCMA form component and record undo state.

    Kept free of any Qt / webview dependency so the builder's save path is
    unit-testable without constructing a QWebEngineView (and so the wiring
    around it stays obvious). Returns True on a successful write.
    """
    timeline = get(Get.TIMELINE, timeline_id)
    if timeline is None:
        return False

    try:
        component = timeline.get_component(component_id)
    except KeyError:
        return False
    if component is None:
        return False

    _, success = timeline.set_component_data(component_id, "annotation_data", jsonld)
    if success:
        # Each save is a discrete, deliberate commit (⌘⏎ in the entry bar — the editor no longer
        # saves live on every keystroke), so it earns its own undo entry. A ⌘⏎ that changed nothing
        # is dropped by the dock's echo guard before it reaches here, so no no-op edit is recorded.
        post(Post.APP_STATE_RECORD, "lcma annotation edit")
    return success
