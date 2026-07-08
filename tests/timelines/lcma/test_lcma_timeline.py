"""Tests for the LCMA form timeline kind.

The LCMA kind is a thin subclass of the Hierarchy kind: it reuses all the
nested-unit machinery and adds a single `annotation_data` (JSON-LD) field plus
its own component/timeline kind. These tests cover the things that are specific
to the subclass — discovery, the new field, and round-trip persistence — and a
couple of inherited-behaviour smoke checks to prove the hierarchy machinery
operates on LCMA units.
"""

from tilia.timelines.base.timeline import Timeline, TimelineFlag
from tilia.timelines.component_kinds import ComponentKind, get_component_class_by_kind
from tilia.timelines.lcma.components import LcmaForm
from tilia.timelines.lcma.timeline import LcmaTimeline


class TestDiscovery:
    def test_recursive_subclasses_includes_lcma(self):
        # LcmaTimeline is a grandchild of Timeline (via HierarchyTimeline); it
        # is only discoverable because subclasses() descends recursively.
        assert LcmaTimeline in Timeline.subclasses()

    def test_get_class_by_name(self):
        assert Timeline.get_class_by_name("Lcma") is LcmaTimeline

    def test_type_name(self):
        assert LcmaTimeline.type_name() == "Lcma"

    def test_component_dispatch(self):
        assert get_component_class_by_kind(ComponentKind.LCMA_FORM) is LcmaForm

    def test_component_kind_and_class(self):
        assert LcmaTimeline.COMPONENT_KIND is ComponentKind.LCMA_FORM
        assert LcmaTimeline.COMPONENT_CLASS is LcmaForm

    def test_not_importable(self):
        # LCMA forms come from the embedded builder, not a CSV — the import
        # command must not be auto-registered for this kind.
        importable = Timeline.get_kinds_by_flag(TimelineFlag.COMPONENTS_IMPORTABLE)
        assert LcmaTimeline not in importable

    def test_copyable(self):
        copyable = Timeline.get_kinds_by_flag(TimelineFlag.COMPONENTS_COPYABLE)
        assert LcmaTimeline in copyable


class TestUIDiscovery:
    def test_element_dispatch(self):
        from tilia.ui.timelines.element_kinds import get_element_class_by_kind
        from tilia.ui.timelines.lcma.element import LcmaFormUI

        assert get_element_class_by_kind(ComponentKind.LCMA_FORM) is LcmaFormUI

    def test_timeline_ui_class(self):
        from tilia.ui.timelines.collection.collection import TimelineUIs
        from tilia.ui.timelines.lcma.timeline import LcmaTimelineUI

        assert TimelineUIs.get_timeline_ui_class(LcmaTimeline) is LcmaTimelineUI


class TestAnnotationData:
    def test_blank_timeline_has_one_lcma_form(self, tls):
        tl = tls.create_timeline(LcmaTimeline)
        assert len(tl) == 1
        assert isinstance(tl[0], LcmaForm)
        assert tl[0].KIND is ComponentKind.LCMA_FORM

    def test_default_empty(self, lcma_form):
        assert lcma_form.annotation_data == ""

    def test_set_and_get(self, lcma_tl, lcma_form):
        jsonld = '{"@context": "https://lcma", "label": "intro"}'
        lcma_tl.set_component_data(lcma_form.id, "annotation_data", jsonld)
        assert lcma_form.annotation_data == jsonld

    def test_validator_rejects_non_string(self, lcma_form):
        _, success = lcma_form.set_data("annotation_data", 123)
        assert success is False

    def test_is_in_serializable(self):
        assert "annotation_data" in LcmaForm.SERIALIZABLE


class TestSerialization:
    def test_state_kind_is_lcma(self, lcma_tl):
        assert lcma_tl.get_state()["kind"] == "Lcma"

    def test_state_includes_annotation_data(self, lcma_tl, lcma_form):
        lcma_tl.set_component_data(lcma_form.id, "annotation_data", '{"x": 1}')
        components = lcma_tl.get_state()["components"]
        assert any(c.get("annotation_data") == '{"x": 1}' for c in components.values())

    def test_roundtrip_preserves_annotation_data(self, tls, lcma_tl, lcma_form):
        jsonld = '{"@context": "https://lcma", "label": "Exposition"}'
        lcma_tl.set_component_data(lcma_form.id, "annotation_data", jsonld)
        components = lcma_tl.get_state()["components"]

        # Reconstruct a fresh timeline from the serialized components, exactly
        # as loading a .tla file does.
        restored = tls.create_timeline(LcmaTimeline, components=components)
        restored_forms = list(restored)
        assert len(restored_forms) == 1
        assert isinstance(restored_forms[0], LcmaForm)
        assert restored_forms[0].annotation_data == jsonld


class TestInheritedHierarchyBehaviour:
    def test_create_child_makes_lcma_form(self, lcma_tl):
        parent = lcma_tl.create_lcma_form(0, 10, 2)[0]
        lcma_tl.create_children([parent])
        children = parent.children
        assert len(children) == 1
        assert isinstance(children[0], LcmaForm)
        assert children[0].level == 1

    def test_split_makes_lcma_forms(self, lcma_tl):
        lcma_tl.create_lcma_form(0, 10, 1)
        lcma_tl.split(5)
        assert len(lcma_tl) == 2
        assert all(isinstance(c, LcmaForm) for c in lcma_tl)
