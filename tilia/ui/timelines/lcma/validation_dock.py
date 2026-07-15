from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWidgets import (
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tilia.exceptions import NoReplyToRequest
from tilia.log import logger
from tilia.requests import (
    Get,
    Post,
    get,
    listen,
    serve,
    stop_listening_to_all,
    stop_serving_all,
)
from tilia.ui.timelines.lcma.session_io import get_session_annotations
from tilia.ui.windows.view_window import ViewDockWidget

# The headless single-file diagnostics engine, vendored from the annotation-ui repo
# (`npm run build:validator` -> dist-validator/validator.html). Self-contained, loaded over
# file://. It exposes window.diagnoseSession(jsonld[]) -> a JSON string of Diagnostic[]; see
# annotation-ui src/validator.ts for the contract this dock drives.
VALIDATOR_HTML = Path(__file__).parent / "validator" / "validator.html"

# Coalesce a burst of unit edits into a single recompute.
_RECOMPUTE_DEBOUNCE_MS = 150

# ✕ / ⚠ — the same error/warning split ValidationPane.tsx renders.
_SEVERITY_ICON = {"error": "✕", "warning": "⚠"}
_SEVERITY_COLOR = {"error": "#c0392b", "warning": "#b9770e"}

_COMPONENT_ID_ROLE = Qt.ItemDataRole.UserRole


class LcmaValidationDock(ViewDockWidget):
    """A dock listing session-wide LCMA validation findings (the "Problems" pane).

    One instance per session (get-or-create via Get.LCMA_VALIDATION), bound to the first LCMA
    timeline. It gathers every unit's JSON-LD (session_io), runs the annotation-ui ``diagnose()``
    lint headlessly in an INVISIBLE QWebEnginePage (validator.html), and lists the findings in a
    native tree — errors first, then warnings (the engine already sorts). Selection is two-way:
    clicking a finding selects the offending unit, scrolls the timeline to it (todo #4) and — through
    the normal on_select path — loads it into the builder; conversely, selecting a unit on the
    timeline mirror-selects its finding row (todo #3, via highlight_unit / clear_highlight). Recomputes,
    debounced, whenever a unit on the bound timeline is created, deleted, or edited.

    The lint itself is NOT reimplemented here: reusing the vendored JS keeps it in step with the
    annotation-ui app, which owns and actively develops the rules.
    """

    # Always-visible: no View-menu toggle / close button, like the builder pane.
    registers_in_view_menu = False

    def __init__(self, timeline_id: int):
        super().__init__("LCMA Validation", menu_title="LCMA Validation")
        self.setObjectName("lcma-validation")
        self.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea
        )

        # The LCMA timeline whose units this dock validates. Bound once, to the first LCMA
        # timeline (see get_or_create_validation_dock): diagnostics are session-scoped — their
        # references resolve within this one unit set.
        self._tl_id = timeline_id
        # index -> component id for the last computed session, so a clicked finding
        # (Diagnostic.index) maps back to the unit it flags.
        self._ordered_ids: list[int] = []
        # The unit whose row is currently mirror-selected (todo #3): set when a unit is selected on
        # the timeline, cleared on its deselect. Kept so the highlight can be re-applied after a
        # recompute rebuilds the tree, and so a stale deselect (deselect-all THEN select on a normal
        # click) doesn't wipe the freshly selected unit's row.
        self._highlighted_id: int | None = None
        # The engine is callable only after validator.html finishes loading; a recompute asked
        # for before then is dropped and subsumed by the initial recompute on load.
        self._engine_ready = False

        self._setup_engine()
        self._setup_ui()

        serve(self, Get.LCMA_VALIDATION, lambda: self)
        for post_ in (Post.TIMELINE_COMPONENT_CREATED, Post.TIMELINE_COMPONENT_DELETED):
            listen(self, post_, self._on_component_added_or_removed)
        listen(
            self,
            Post.TIMELINE_COMPONENT_SET_DATA_DONE,
            self._on_component_set_data_done,
        )

        main_window = get(Get.MAIN_WINDOW)
        self.setParent(main_window)
        main_window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self)

    # --- setup ---

    def _setup_engine(self):
        # An INVISIBLE page (no QWebEngineView): TiLiA never shows the validator, it only calls
        # diagnoseSession over runJavaScript and renders the result natively below.
        self._page = QWebEnginePage(self)
        self._page.loadFinished.connect(self._on_engine_loaded)
        self._page.load(QUrl.fromLocalFile(str(VALIDATOR_HTML.resolve())))

        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_RECOMPUTE_DEBOUNCE_MS)
        self._debounce.timeout.connect(self._recompute)

    def _setup_ui(self):
        self._summary = QLabel()
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setRootIsDecorated(False)
        self._tree.itemClicked.connect(self._on_item_clicked)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self._summary)
        layout.addWidget(self._tree, stretch=1)
        self.setWidget(container)
        self._render([])  # clean state until the engine first reports

    # --- engine lifecycle ---

    def _on_engine_loaded(self, ok: bool):
        if not ok:
            logger.error("LCMA validation: engine (validator.html) failed to load")
            return
        self._engine_ready = True
        self._recompute()  # initial paint; also catches units present at load (file open)

    # --- refresh triggers ---

    def _on_component_added_or_removed(self, _timeline_class, timeline_id, *_):
        # CREATED/DELETED are posted as (timeline_class, timeline_id, ...).
        if timeline_id == self._tl_id:
            self._schedule_recompute()

    def _on_component_set_data_done(self, timeline_id, *_):
        # SET_DATA_DONE is posted as (timeline_id, component_id, ...). Fires for any field (e.g. a
        # handle drag), not just annotation_data — recompute is debounced and cheap, so we don't
        # filter by attribute.
        if timeline_id == self._tl_id:
            self._schedule_recompute()

    def _schedule_recompute(self):
        self._debounce.start()  # (re)start; a burst collapses into one recompute

    # --- compute ---

    def _recompute(self):
        if not self._engine_ready:
            return
        pairs = get_session_annotations(self._tl_id)
        self._ordered_ids = [cmp_id for cmp_id, _ in pairs]
        jsonld = [data for _, data in pairs]
        self._page.runJavaScript(
            f"diagnoseSession({json.dumps(jsonld)})", self._on_diagnostics
        )

    def _on_diagnostics(self, result: str | None):
        if result is None:
            logger.error(
                "LCMA validation: diagnoseSession returned nothing (engine error?)"
            )
            return
        try:
            diagnostics = json.loads(result)
        except (TypeError, ValueError):
            logger.error("LCMA validation: engine returned non-JSON: %r", result)
            return
        self._render(diagnostics)
        self._update_element_markers(diagnostics)

    # --- render ---

    def _render(self, diagnostics: list[dict]):
        self._tree.clear()
        errors = sum(1 for d in diagnostics if d.get("severity") == "error")
        warnings = len(diagnostics) - errors
        self._summary.setText(self._summary_text(errors, warnings))

        if not diagnostics:
            hint = QTreeWidgetItem(["No reference or vocabulary problems."])
            hint.setFlags(Qt.ItemFlag.NoItemFlags)  # non-selectable reassurance row
            self._tree.addTopLevelItem(hint)
            return

        for d in diagnostics:
            severity = d.get("severity", "error")
            name = d.get("name") or ""
            index = d.get("index", -1)
            where = f"#{index + 1}" + (f" {name}" if name else "")
            item = QTreeWidgetItem(
                [
                    f"{_SEVERITY_ICON.get(severity, '')}  {where} — {d.get('message', '')}"
                ]
            )
            color = _SEVERITY_COLOR.get(severity)
            if color:
                item.setForeground(0, QBrush(QColor(color)))
            if 0 <= index < len(self._ordered_ids):
                item.setData(0, _COMPONENT_ID_ROLE, self._ordered_ids[index])
            self._tree.addTopLevelItem(item)

        # clear() above dropped the selection; restore the selected unit's row (if it still has a
        # finding) so editing a unit doesn't lose its mirror-highlight on the ensuing recompute.
        self._reapply_highlight()

    @staticmethod
    def _summary_text(errors: int, warnings: int) -> str:
        if not errors and not warnings:
            return "Validation: clean"
        parts = []
        if errors:
            parts.append(f"{errors} error" + ("s" if errors != 1 else ""))
        if warnings:
            parts.append(f"{warnings} warning" + ("s" if warnings != 1 else ""))
        return "Validation: " + ", ".join(parts)

    # --- per-unit error markers (todo #3) ---

    def _update_element_markers(self, diagnostics: list[dict]) -> None:
        """Flag each validated unit's element with whether the lint found an ERROR on it, so the
        element paints (or clears) the ⊗ marker. Every unit in the last computed session is set
        explicitly — True for the flagged ones, False for the rest — so a fixed error clears on the
        next recompute. Diagnose-driven: the element never runs the lint itself. Warnings (incl. the
        ⚠ proposed-term badge, which is the unit's OWN data) are intentionally not mirrored here —
        only errors get the element marker."""
        error_ids = set()
        for d in diagnostics:
            if d.get("severity") != "error":
                continue
            index = d.get("index", -1)
            if 0 <= index < len(self._ordered_ids):
                error_ids.add(self._ordered_ids[index])
        for cmp_id in self._ordered_ids:
            try:
                element = get(Get.TIMELINE_UI_ELEMENT, self._tl_id, cmp_id)
            except NoReplyToRequest:
                continue
            if element is not None:
                element.set_validation_error(cmp_id in error_ids)

    # --- click -> select + reveal the flagged unit (todo #4) ---

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int):
        cmp_id = item.data(0, _COMPONENT_ID_ROLE)
        if cmp_id is None:
            return
        try:
            element = get(Get.TIMELINE_UI_ELEMENT, self._tl_id, cmp_id)
        except NoReplyToRequest:
            return
        if element is None:
            return
        # Reuse the normal selection path: select_element -> on_select loads the unit into the
        # builder, so a clicked finding both highlights the unit and opens it for editing.
        element.timeline_ui.deselect_all_elements()
        element.timeline_ui.select_element(element)
        # todo #4: scroll the timeline so the unit is on screen — a finding is useless if you can't
        # see the unit it flags. center_on_time is the same horizontal-centring the auto-scroll uses;
        # we centre on the unit's start (its left edge), so the whole band opens to its right.
        element.timeline_ui.collection.center_on_time(element.get_data("start"))

    # --- timeline selection -> mirror-highlight the unit's row (todo #3) ---

    def highlight_unit(self, component_id: int) -> None:
        """Select this unit's finding row, mirroring a timeline selection into the Problems pane so
        the active unit's finding is visible without hunting for it. A unit with no finding clears
        the selection instead (nothing to point at). Driven from LcmaFormUI.on_select; the reverse of
        _on_item_clicked, so pane and timeline stay in sync both ways."""
        self._highlighted_id = component_id
        item = self._find_item_for_component(component_id)
        if item is None:
            self._clear_selection()
            return
        self._tree.setCurrentItem(item)
        self._tree.scrollToItem(item)

    def clear_highlight(self, component_id: int) -> None:
        """Drop the mirror-highlight when its unit is deselected. Scoped by id: on a normal click the
        old unit's deselect can arrive AFTER the new unit's select (deselect-all then select), and
        this guard keeps that stale deselect from wiping the new unit's highlight."""
        if self._highlighted_id != component_id:
            return
        self._highlighted_id = None
        self._clear_selection()

    def _reapply_highlight(self) -> None:
        # Re-select the tracked unit's row after a recompute rebuilt the tree. No scrollToItem here:
        # a recompute (e.g. the user edited the unit) shouldn't yank the pane's scroll position.
        if self._highlighted_id is None:
            return
        item = self._find_item_for_component(self._highlighted_id)
        if item is not None:
            self._tree.setCurrentItem(item)

    def _find_item_for_component(self, component_id: int) -> QTreeWidgetItem | None:
        for i in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(i)
            if item.data(0, _COMPONENT_ID_ROLE) == component_id:
                return item
        return None

    def _clear_selection(self) -> None:
        self._tree.clearSelection()
        self._tree.setCurrentItem(None)

    def deleteLater(self):
        stop_listening_to_all(self)
        stop_serving_all(self)
        super().deleteLater()


def get_or_create_validation_dock(timeline_id: int) -> LcmaValidationDock:
    try:
        return get(Get.LCMA_VALIDATION)
    except NoReplyToRequest:
        return LcmaValidationDock(timeline_id)


def get_validation_dock_if_exists() -> LcmaValidationDock | None:
    try:
        return get(Get.LCMA_VALIDATION)
    except NoReplyToRequest:
        return None
