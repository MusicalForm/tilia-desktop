from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, QUrl, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QFormLayout, QLabel, QTextEdit, QVBoxLayout, QWidget

from tilia.exceptions import NoReplyToRequest
from tilia.log import logger
from tilia.requests import (
    Get,
    Post,
    get,
    listen,
    post,
    serve,
    stop_listening_to_all,
    stop_serving_all,
)
from tilia.ui.timelines.lcma.builder_io import set_annotation_data
from tilia.ui.timelines.lcma.session_io import get_session_annotations
from tilia.ui.windows.view_window import ViewDockWidget

# The single-file React annotation builder, vendored from the annotation-ui
# repo (`npm run build:embed` -> dist-embed/embed.html). Self-contained, loaded
# over file://. The JS side connects back over QWebChannel — see annotation-ui
# src/embed.tsx for the contract this dock implements.
EMBED_HTML = Path(__file__).parent / "builder" / "embed.html"

# Coalesce a burst of sibling-unit edits into a single session-names push to the builder.
_SESSION_UNITS_DEBOUNCE_MS = 150


class LcmaBuilderBackend(QObject):
    """The Python object the builder reaches over QWebChannel as ``backend``.

    Slot names mirror the TiliaBackend interface in annotation-ui src/embed.ts.
    """

    def __init__(self, dock: LcmaBuilderDock):
        super().__init__()
        self._dock = dock

    @Slot()
    def ready(self):
        # The builder mounted and connected the channel; window.loadAnnotation
        # is now defined, so it is safe to push the selected unit's annotation.
        self._dock.on_bridge_ready()

    @Slot(str)
    def save_annotation(self, jsonld: str):
        self._dock.on_save_annotation(jsonld)

    @Slot(str)
    def report_error(self, message: str):
        logger.error("LCMA builder: %s", message)


class LcmaBuilderDock(ViewDockWidget):
    """A dock hosting the embedded LCMA annotation builder.

    One instance per session (get-or-create via Get.LCMA_BUILDER). It follows
    timeline selection: selecting an LCMA unit pushes that unit's JSON-LD into
    the builder; a committed edit (⌘⏎ in the entry bar) is written back onto the
    unit. The bar surfaces "⌘⏎ save" itself, so the dock adds no save affordance.
    """

    # Always-visible: no View-menu toggle (ViewDockWidget already gives it no close button), so
    # the pane can't be hidden once an LCMA timeline brings it up.
    registers_in_view_menu = False

    def __init__(self):
        super().__init__("LCMA Annotation Builder", menu_title="LCMA Builder")
        self.setObjectName("lcma-builder")
        self.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea
        )

        # The unit currently bound to the builder, and bookkeeping to push the
        # annotation only once the JS side is live.
        self._tl_id: int | None = None
        self._cmp_id: int | None = None
        self._bridge_ready = False
        self._pending: str | None = None
        # Last value we pushed to (or received from) the builder for the bound
        # unit — used to ignore a save that merely echoes what we just loaded.
        self._last_value: str | None = None

        self._setup_web_engine()
        self._setup_ui()

        # Debounce re-pushing the session's unit names to the builder: a burst of sibling edits
        # collapses into one setSessionUnits call.
        self._session_units_timer = QTimer(self)
        self._session_units_timer.setSingleShot(True)
        self._session_units_timer.setInterval(_SESSION_UNITS_DEBOUNCE_MS)
        self._session_units_timer.timeout.connect(self._push_session_units)

        serve(self, Get.LCMA_BUILDER, lambda: self)
        # Keep the header's start/end live and the auto-name numbering current: an edit on the bound
        # unit posts TIMELINE_COMPONENT_SET_DATA_DONE (re-reads the inspector values), while creating
        # or deleting any unit on the bound timeline changes the sibling names autoName numbers against.
        for post_ in (Post.TIMELINE_COMPONENT_CREATED, Post.TIMELINE_COMPONENT_DELETED):
            listen(self, post_, self.on_component_added_or_removed)
        listen(
            self,
            Post.TIMELINE_COMPONENT_SET_DATA_DONE,
            self.on_component_set_data_done,
        )

        main_window = get(Get.MAIN_WINDOW)
        self.setParent(main_window)
        main_window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self)

    def _setup_web_engine(self):
        self.view = QWebEngineView()
        self.view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        self.channel = QWebChannel()
        self.backend = LcmaBuilderBackend(self)
        self.channel.registerObject("backend", self.backend)
        self.view.page().setWebChannel(self.channel)
        self.view.load(QUrl.fromLocalFile(str(EMBED_HTML.resolve())))

    def _setup_ui(self):
        # The bound unit's temporal bounds + comments sit in a detail panel BELOW the builder, so
        # the whole unit is edited in one pane (LCMA units opt out of the shared Inspector). The
        # LCMA annotation builder (the web view) takes the top and the stretch; the read-only
        # start/end and the editable comments hang beneath it. Start/end are set by dragging the
        # unit's handles; comments write back through the same INSPECTOR_FIELD_EDITED path the
        # Inspector uses.
        # Guards a programmatic comments refresh from echoing back as an edit.
        self._suppress_comments_signal = False
        self._start_end_label = QLabel("—")
        self._start_end_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._comments_edit = QTextEdit()
        self._comments_edit.setAcceptRichText(False)
        self._comments_edit.setMaximumHeight(80)
        self._comments_edit.textChanged.connect(self._on_comments_changed)

        form = QFormLayout()
        form.addRow("Start / end", self._start_end_label)
        form.addRow("Comments", self._comments_edit)
        detail_panel = QWidget()
        detail_panel.setLayout(form)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view, stretch=1)
        layout.addWidget(detail_panel)
        self.setWidget(container)

    # --- bridge callbacks (called from the QWebChannel backend) ---

    def on_bridge_ready(self):
        self._bridge_ready = True
        if self._pending is not None:
            self._push_to_js(self._pending)
            self._pending = None
        self._push_session_units()

    def on_save_annotation(self, jsonld: str):
        if self._tl_id is None or self._cmp_id is None:
            return
        if jsonld == self._last_value:
            # A ⌘⏎ commit that changed nothing (same JSON-LD we last loaded or saved). With
            # discrete commits this is load-bearing, not just defensive: it stops an unchanged
            # commit from writing and recording a no-op undo entry. (Programmatic loads never
            # save, so they can't echo here.)
            return
        self._last_value = jsonld
        set_annotation_data(self._tl_id, self._cmp_id, jsonld)

    # --- driven by selection (called from LcmaFormUI) ---

    def load_annotation(self, timeline_id: int, component_id: int, jsonld: str):
        self._tl_id = timeline_id
        self._cmp_id = component_id
        self._last_value = jsonld
        if not self.isVisible():
            self.show()
        self._refresh_header()
        self._push_or_queue(jsonld)
        self._push_session_units()

    def clear_annotation(self, component_id: int):
        # Only clear if the deselected unit is the one currently bound, so a
        # deselect cascade doesn't wipe a freshly-selected unit.
        if component_id != self._cmp_id:
            return
        self._tl_id = None
        self._cmp_id = None
        self._last_value = ""
        self._refresh_header()  # ids now None -> blanks the header
        self._push_or_queue("")  # empty -> the builder shows a blank label
        self._push_session_units()  # tl_id now None -> clears the builder's name list

    def focus_editor(self):
        # Enter/Return over a selected LCMA unit routes here instead of raising the shared
        # Inspector (which LCMA units opt out of). Bring the pane forward and hand keyboard focus
        # to the annotation builder's entry bar so the user can start typing at once.
        if not self.isVisible():
            self.show()
        self.raise_()
        self.view.setFocus()

    # --- header (start/end + comments for the bound unit) ---

    def on_component_added_or_removed(self, _timeline_class, timeline_id, *_):
        # CREATED/DELETED are posted as (timeline_class, timeline_id, ...). A new or removed sibling
        # changes the names autoName numbers against, so refresh the builder's session list.
        if timeline_id == self._tl_id:
            self._schedule_session_units_refresh()

    def on_component_set_data_done(self, timeline_id, component_id, *_):
        # SET_DATA_DONE is posted as (timeline_id, component_id, ...). Any unit's edit on the bound
        # timeline can rename it, so refresh the session names; the header only tracks the bound unit.
        if timeline_id != self._tl_id:
            return
        self._schedule_session_units_refresh()
        if component_id == self._cmp_id:
            self._refresh_header()

    def _refresh_header(self):
        if self._tl_id is None or self._cmp_id is None:
            self._start_end_label.setText("—")
            self._set_comments_text("")
            return
        try:
            element = get(Get.TIMELINE_UI_ELEMENT, self._tl_id, self._cmp_id)
        except NoReplyToRequest:
            return
        if element is None:
            return
        fields = element.get_inspector_dict()
        self._start_end_label.setText(fields.get("Start / end") or "—")
        self._set_comments_text(fields.get("Comments") or "")

    def _set_comments_text(self, text: str):
        if self._comments_edit.toPlainText() == text:
            return
        self._suppress_comments_signal = True
        self._comments_edit.setPlainText(text)
        self._suppress_comments_signal = False

    def _on_comments_changed(self):
        # Mirror the Inspector's edit path: post INSPECTOR_FIELD_EDITED for "Comments" and let the
        # selected element apply it (no-op guard + undo-burst collapse keyed on this dock's id).
        # Suppressed while a programmatic refresh sets the text, so a refresh can't echo back.
        if self._suppress_comments_signal or self._cmp_id is None:
            return
        post(
            Post.INSPECTOR_FIELD_EDITED,
            "Comments",
            self._comments_edit.toPlainText(),
            self._cmp_id,
            id(self),
        )

    # --- internals ---

    def _push_or_queue(self, jsonld: str):
        if self._bridge_ready:
            self._push_to_js(jsonld)
        else:
            self._pending = jsonld

    def _push_to_js(self, jsonld: str):
        self.view.page().runJavaScript(f"loadAnnotation({json.dumps(jsonld)})")

    def _schedule_session_units_refresh(self):
        self._session_units_timer.start()  # (re)start; a burst collapses into one push

    def _push_session_units(self):
        # Push the OTHER units' JSON-LD so the builder's autoName numbers a blank commit against the
        # session (v -> v2 -> v3). The bound unit is excluded: it must not seed its own auto-name and
        # is already loaded in the bar. No-op until the JS bridge is up (redone from on_bridge_ready).
        # Never-committed units (empty JSON-LD) are dropped.
        if not self._bridge_ready:
            return
        pairs = get_session_annotations(self._tl_id) if self._tl_id is not None else []
        others = [data for cmp_id, data in pairs if cmp_id != self._cmp_id and data]
        self.view.page().runJavaScript(f"setSessionUnits({json.dumps(others)})")

    def deleteLater(self):
        stop_listening_to_all(self)
        stop_serving_all(self)
        super().deleteLater()


def get_or_create_builder_dock() -> LcmaBuilderDock:
    try:
        return get(Get.LCMA_BUILDER)
    except NoReplyToRequest:
        return LcmaBuilderDock()


def get_builder_dock_if_exists() -> LcmaBuilderDock | None:
    try:
        return get(Get.LCMA_BUILDER)
    except NoReplyToRequest:
        return None
