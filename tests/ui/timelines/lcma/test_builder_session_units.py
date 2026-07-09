"""The builder dock pushes the OTHER units' JSON-LD to the embed (setSessionUnits) so the JS
autoName numbers a blank commit against the session (v -> v2 -> v3). Before this the embed
hardcoded an empty unit list, so every unit got the bare abbreviation and nothing incremented.

The embed's autoName / name extraction is JS and is covered by the annotation-ui suite; here the
runJavaScript boundary is stubbed (like test_validation_dock) so the Python gathering, bound-unit
exclusion, empty-unit drop, bridge gating, and refresh filtering are tested without a live webview.

The dock is eager-created by the lcma_tlui fixture (LcmaTimelineUI.__init__); the tests fetch that
instance and swap its view for a fake rather than booting a real QWebEngineView.
"""

import json


def _builder_dock():
    from tilia.ui.timelines.lcma.builder_dock import get_builder_dock_if_exists

    return get_builder_dock_if_exists()


class _FakePage:
    def __init__(self):
        self.calls = []

    def runJavaScript(self, js):
        self.calls.append(js)


class _FakeView:
    """Stand-in for the QWebEngineView: captures the JS the dock would run in the embed."""

    def __init__(self):
        self._page = _FakePage()

    def page(self):
        return self._page


def _bind_fake_view(dock, bridge_ready=True):
    view = _FakeView()
    dock.view = view
    dock._bridge_ready = bridge_ready
    return view


def _session_units_payload(js: str) -> list[str]:
    """The JSON-LD list from a captured ``setSessionUnits([...])`` call."""
    assert js.startswith("setSessionUnits(") and js.endswith(")")
    return json.loads(js[len("setSessionUnits(") : -1])


def _last_session_units(view: _FakeView) -> list[str]:
    pushes = [c for c in view.page().calls if c.startswith("setSessionUnits(")]
    assert pushes, f"no setSessionUnits push in {view.page().calls}"
    return _session_units_payload(pushes[-1])


class TestPushSessionUnits:
    def test_excludes_bound_unit_and_empty_units(self, lcma_tlui, lcma_tl):
        dock = _builder_dock()
        view = _bind_fake_view(dock)
        a = lcma_tl.create_lcma_form(0, 1, 1)[0]
        b = lcma_tl.create_lcma_form(1, 2, 1)[0]
        lcma_tl.create_lcma_form(2, 3, 1)  # c: left with empty annotation_data
        lcma_tl.set_component_data(a.id, "annotation_data", '{"name":"v"}')
        lcma_tl.set_component_data(b.id, "annotation_data", '{"name":"pt"}')

        dock._tl_id = lcma_tl.id
        dock._cmp_id = b.id  # b is the unit loaded in the bar
        view.page().calls.clear()
        dock._push_session_units()

        # a is pushed; b is excluded (the bound unit must not seed its own auto-name); c is dropped
        # (never committed -> empty JSON-LD).
        assert _last_session_units(view) == ['{"name":"v"}']

    def test_noop_until_bridge_ready(self, lcma_tlui, lcma_tl):
        dock = _builder_dock()
        view = _bind_fake_view(dock, bridge_ready=False)
        unit = lcma_tl.create_lcma_form(0, 1, 1)[0]
        lcma_tl.set_component_data(unit.id, "annotation_data", '{"name":"v"}')
        dock._tl_id = lcma_tl.id
        dock._cmp_id = None

        dock._push_session_units()

        assert (
            view.page().calls == []
        )  # queued push happens from on_bridge_ready instead

    def test_pushes_on_bridge_ready(self, lcma_tlui, lcma_tl):
        dock = _builder_dock()
        view = _bind_fake_view(dock, bridge_ready=False)
        unit = lcma_tl.create_lcma_form(0, 1, 1)[0]
        lcma_tl.set_component_data(unit.id, "annotation_data", '{"name":"v"}')
        dock._tl_id = lcma_tl.id
        dock._cmp_id = None

        dock.on_bridge_ready()

        assert _last_session_units(view) == ['{"name":"v"}']

    def test_no_bound_timeline_pushes_empty(self, lcma_tlui, lcma_tl):
        # After a deselect (_tl_id None) the builder's name list is cleared, not left stale.
        dock = _builder_dock()
        view = _bind_fake_view(dock)
        dock._tl_id = None
        dock._cmp_id = None
        view.page().calls.clear()

        dock._push_session_units()

        assert _last_session_units(view) == []


class TestLoadAnnotationPushesSessionUnits:
    def test_load_pushes_both_annotation_and_session_units(self, lcma_tlui, lcma_tl):
        dock = _builder_dock()
        view = _bind_fake_view(dock)
        other = lcma_tl.create_lcma_form(0, 1, 1)[0]
        lcma_tl.set_component_data(other.id, "annotation_data", '{"name":"v"}')
        target = lcma_tl.create_lcma_form(1, 2, 1)[0]
        view.page().calls.clear()

        dock.load_annotation(lcma_tl.id, target.id, "")

        kinds = [c.split("(", 1)[0] for c in view.page().calls]
        assert "loadAnnotation" in kinds and "setSessionUnits" in kinds
        # the sibling name is offered; the just-loaded (blank) target is not
        assert _last_session_units(view) == ['{"name":"v"}']


class TestRefreshFilter:
    def test_create_delete_on_bound_timeline_schedules_refresh_others_ignored(
        self, lcma_tlui, monkeypatch
    ):
        dock = _builder_dock()
        calls = []
        monkeypatch.setattr(
            dock, "_schedule_session_units_refresh", lambda: calls.append(True)
        )
        dock._tl_id = 42
        dock._cmp_id = None
        dock.on_component_added_or_removed(object, 42)  # bound timeline
        dock.on_component_added_or_removed(object, 99)  # a different timeline
        assert calls == [True]

    def test_set_data_on_bound_timeline_schedules_refresh_others_ignored(
        self, lcma_tlui, monkeypatch
    ):
        dock = _builder_dock()
        calls = []
        monkeypatch.setattr(
            dock, "_schedule_session_units_refresh", lambda: calls.append(True)
        )
        dock._tl_id = 42
        dock._cmp_id = None  # != the component id below, so no header refresh path
        dock.on_component_set_data_done(42, 7)  # bound timeline
        dock.on_component_set_data_done(99, 7)  # a different timeline
        assert calls == [True]
