from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

from tilia.exceptions import NoReplyToRequest
from tilia.log import logger
from tilia.requests import Get, get, serve, stop_serving_all
from tilia.ui.timelines.lcma.builder_io import set_annotation_data
from tilia.ui.windows.view_window import ViewDockWidget

# The single-file React annotation builder, vendored from the annotation-ui
# repo (`npm run build:embed` -> dist-embed/embed.html). Self-contained, loaded
# over file://. The JS side connects back over QWebChannel — see annotation-ui
# src/embed.tsx for the contract this dock implements.
EMBED_HTML = Path(__file__).parent / "builder" / "embed.html"


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
        serve(self, Get.LCMA_BUILDER, lambda: self)

        main_window = get(Get.MAIN_WINDOW)
        self.setParent(main_window)
        main_window.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self)

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
        self.setWidget(self.view)

    # --- bridge callbacks (called from the QWebChannel backend) ---

    def on_bridge_ready(self):
        self._bridge_ready = True
        if self._pending is not None:
            self._push_to_js(self._pending)
            self._pending = None

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
        self._push_or_queue(jsonld)

    def clear_annotation(self, component_id: int):
        # Only clear if the deselected unit is the one currently bound, so a
        # deselect cascade doesn't wipe a freshly-selected unit.
        if component_id != self._cmp_id:
            return
        self._tl_id = None
        self._cmp_id = None
        self._last_value = ""
        self._push_or_queue("")  # empty -> the builder shows a blank label

    # --- internals ---

    def _push_or_queue(self, jsonld: str):
        if self._bridge_ready:
            self._push_to_js(jsonld)
        else:
            self._pending = jsonld

    def _push_to_js(self, jsonld: str):
        self.view.page().runJavaScript(f"loadAnnotation({json.dumps(jsonld)})")

    def deleteLater(self):
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
