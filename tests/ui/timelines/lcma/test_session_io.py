"""Backend test for session_io.get_session_annotations — the ordered (id, JSON-LD) list the
validation dock feeds to the diagnostics engine. Qt-free (session_io pulls no webview), so it
lives with the other backend LCMA logic rather than the live-dock suite."""

from tilia.ui.timelines.lcma.session_io import get_session_annotations


class TestGetSessionAnnotations:
    def test_returns_empty_for_unknown_timeline(self):
        assert get_session_annotations(9999) == []

    def test_returns_empty_for_timeline_with_no_units(self, lcma_tl):
        assert get_session_annotations(lcma_tl.id) == []

    def test_orders_by_ordering_attrs_and_pairs_id_with_annotation_data(self, lcma_tl):
        # Created out of natural order; the result must come back in ORDERING_ATTRS order
        # (level, start) so a Diagnostic.index maps to a stable unit across recomputes.
        later = lcma_tl.create_lcma_form(2, 3, 1)[0]
        earlier = lcma_tl.create_lcma_form(0, 1, 1)[0]
        lcma_tl.set_component_data(later.id, "annotation_data", '{"name":"later"}')
        lcma_tl.set_component_data(earlier.id, "annotation_data", '{"name":"earlier"}')

        assert get_session_annotations(lcma_tl.id) == [
            (earlier.id, '{"name":"earlier"}'),
            (later.id, '{"name":"later"}'),
        ]

    def test_unit_with_no_annotation_data_yields_empty_string(self, lcma_tl):
        unit = lcma_tl.create_lcma_form(0, 1, 1)[0]
        assert get_session_annotations(lcma_tl.id) == [(unit.id, "")]
