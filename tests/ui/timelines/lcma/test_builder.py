"""Tests for the LCMA builder wiring — the save path (builder -> component) and
the selection path (select unit -> builder loads it).

The QWebEngineView dock itself (boot under file://, QWebChannel handshake, JS
round-trip) is proven end-to-end by the standalone embed spike in the
annotation-ui repo and by manual in-app verification; here we cover the Python
logic around it without constructing a webview.
"""

from tilia.requests import Post, listen, stop_listening_to_all
from tilia.ui.timelines.lcma import builder_io


class StateRecordCounter:
    def __init__(self):
        self.records = []
        listen(self, Post.APP_STATE_RECORD, self._on_record)

    def _on_record(self, *args, **kwargs):
        self.records.append((args, kwargs))

    def stop(self):
        stop_listening_to_all(self)


class TestSetAnnotationData:
    def test_writes_to_component(self, lcma_tl, lcma_form):
        ok = builder_io.set_annotation_data(lcma_tl.id, lcma_form.id, '{"label": "A"}')
        assert ok is True
        assert lcma_form.annotation_data == '{"label": "A"}'

    def test_records_undo_state(self, lcma_tl, lcma_form):
        counter = StateRecordCounter()
        try:
            builder_io.set_annotation_data(lcma_tl.id, lcma_form.id, '{"x": 1}')
            assert counter.records  # at least one APP_STATE_RECORD posted
        finally:
            counter.stop()

    def test_unknown_timeline_returns_false(self, lcma_form):
        assert builder_io.set_annotation_data(-999, lcma_form.id, "{}") is False

    def test_unknown_component_returns_false(self, lcma_tl):
        assert builder_io.set_annotation_data(lcma_tl.id, -999, "{}") is False


class _FakeDock:
    def __init__(self):
        self.loaded = []
        self.cleared = []

    def load_annotation(self, tl_id, cmp_id, jsonld):
        self.loaded.append((tl_id, cmp_id, jsonld))

    def clear_annotation(self, cmp_id):
        self.cleared.append(cmp_id)


class TestSelectionWiring:
    def test_select_loads_annotation_into_builder(
        self, lcma_tlui, lcma_form, monkeypatch
    ):
        import tilia.ui.timelines.lcma.builder_dock as bd

        fake = _FakeDock()
        monkeypatch.setattr(bd, "get_or_create_builder_dock", lambda: fake)

        lcma_tlui.timeline.set_component_data(
            lcma_form.id, "annotation_data", '{"a": 1}'
        )
        ui = lcma_tlui.get_element(lcma_form.id)
        lcma_tlui.select_element(ui)

        assert fake.loaded
        tl_id, cmp_id, jsonld = fake.loaded[-1]
        assert tl_id == lcma_tlui.id
        assert cmp_id == lcma_form.id
        assert jsonld == '{"a": 1}'

    def test_deselect_clears_builder(self, lcma_tlui, lcma_form, monkeypatch):
        import tilia.ui.timelines.lcma.builder_dock as bd

        fake = _FakeDock()
        monkeypatch.setattr(bd, "get_or_create_builder_dock", lambda: fake)
        monkeypatch.setattr(bd, "get_builder_dock_if_exists", lambda: fake)

        ui = lcma_tlui.get_element(lcma_form.id)
        lcma_tlui.select_element(ui)
        lcma_tlui.deselect_element(ui)

        assert fake.cleared == [lcma_form.id]
