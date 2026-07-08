"""Layout, visibility and Enter-focus of the LCMA builder pane.

Covers the four "LCMA pane" todos:
  * the dock is docked on the LEFT (item 3)
  * the annotation builder (web view) sits ABOVE the start/end + comments detail panel (item 2)
  * the dock is created and shown as soon as an LCMA timeline exists — no unit selection needed —
    and can't be hidden by the user (item 1)
  * Enter over a selected LCMA unit focuses this dock instead of opening the shared Inspector,
    which LCMA units opt out of (item 5)

The webview boot / QWebChannel round-trip is covered by test_dock_live.py; these tests exercise
the surrounding Qt wiring. builder_dock is imported inside the tests (not at module scope) so
collecting the suite doesn't pull QtWebEngine into non-LCMA runs — the same convention the other
LCMA UI test files follow.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDockWidget

from tilia.requests import Get, get
from tilia.ui.windows.kinds import WindowKind


def _new_dock():
    from tilia.ui.timelines.lcma.builder_dock import LcmaBuilderDock

    return LcmaBuilderDock()


def _existing_dock():
    from tilia.ui.timelines.lcma.builder_dock import get_builder_dock_if_exists

    return get_builder_dock_if_exists()


class TestDockPosition:
    def test_dock_is_added_on_the_left(self, lcma_tlui):
        # Item 3: the pane opens on the left, not the right.
        dock = _existing_dock()
        assert dock is not None  # eager-created when the LCMA timeline UI was built
        main_window = get(Get.MAIN_WINDOW)
        assert main_window.dockWidgetArea(dock) == Qt.DockWidgetArea.LeftDockWidgetArea


class TestDockLayoutOrder:
    def test_web_builder_sits_above_detail_panel(self):
        # Item 2: the annotation builder (web view) is on top and takes the stretch; the read-only
        # start/end and the editable comments hang in a panel beneath it.
        dock = _new_dock()
        try:
            layout = dock.widget().layout()
            assert layout.itemAt(0).widget() is dock.view
            assert layout.stretch(0) == 1

            detail_panel = layout.itemAt(1).widget()
            assert layout.stretch(1) == 0
            assert dock._start_end_label.parentWidget() is detail_panel
            assert dock._comments_edit.parentWidget() is detail_panel
        finally:
            dock.deleteLater()


class TestAlwaysVisible:
    def test_builder_shown_when_lcma_timeline_exists_without_selection(self, lcma_tlui):
        # Item 1: building an LCMA timeline UI brings the pane up on its own — no unit selected.
        dock = _existing_dock()
        assert dock is not None
        assert not dock.isHidden()

    def test_dock_is_not_user_hideable(self):
        # Item 1: no View-menu toggle registration + no close button => the user can't hide it.
        from tilia.ui.timelines.lcma.builder_dock import LcmaBuilderDock

        assert LcmaBuilderDock.registers_in_view_menu is False
        dock = _new_dock()
        try:
            dock.show()
            # showEvent skipped the WINDOW_UPDATE_STATE registration that feeds the View menu.
            assert dock.is_registered is False
            assert not (
                dock.features() & QDockWidget.DockWidgetFeature.DockWidgetClosable
            )
        finally:
            dock.deleteLater()


class TestEnterFocusesBuilder:
    def test_enter_on_lcma_unit_focuses_builder_not_inspector(
        self, qtui, lcma_tlui, lcma_form, monkeypatch
    ):
        # Item 5: Enter/Return runs timeline.element.inspect -> on_timeline_element_inspect. For a
        # selected LCMA unit (INSPECTABLE = False) it must focus the builder pane, not raise the
        # shared Inspector. The inspectable path (else -> on_window_open) stays covered by the
        # Inspector/inspectable-timeline suites.
        ui = lcma_tlui.get_element(lcma_form.id)
        lcma_tlui.select_element(ui)

        focused = []
        opened = []
        monkeypatch.setattr(ui, "focus_dedicated_editor", lambda: focused.append(True))
        monkeypatch.setattr(qtui, "on_window_open", lambda kind: opened.append(kind))

        qtui.on_timeline_element_inspect()

        assert focused == [True]
        assert WindowKind.INSPECT not in opened
