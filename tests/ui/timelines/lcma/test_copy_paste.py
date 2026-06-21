"""annotation_data must survive copy/paste. HierarchyUI's DEFAULT_COPY_ATTRIBUTES omits it,
and the hierarchy copy used to read HierarchyUI's attrs by class (dropping any subclass field).
The fix: the copy reads each element's OWN attrs, LcmaFormUI adds annotation_data, and paste
skips attrs the target lacks so a cross-kind paste degrades cleanly instead of crashing.
"""

from tilia.ui.timelines.copy_paste import paste_into_element

JSONLD = '{"name": "X", "forms": [{"@type": "lcma:Form", "function": {"hasCategory": "fn:basic_idea"}}]}'


def test_copy_data_includes_annotation_data(lcma_tlui, lcma_form):
    el = lcma_tlui.get_element(lcma_form.id)
    el.set_data("annotation_data", JSONLD)
    copy_data = lcma_tlui.get_copy_data_from_hierarchy_ui(el)
    assert copy_data["values"]["annotation_data"] == JSONLD


def test_paste_restores_annotation_data_into_another_lcma_unit(
    lcma_tlui, lcma_tl, lcma_form
):
    src = lcma_tlui.get_element(lcma_form.id)
    src.set_data("annotation_data", JSONLD)
    copy_data = lcma_tlui.get_copy_data_from_hierarchy_ui(src)

    dst_cmp = lcma_tl.create_lcma_form(2, 3, 1)[0]
    dst = lcma_tlui.get_element(dst_cmp.id)
    assert dst.get_data("annotation_data") == ""  # starts empty

    paste_into_element(dst, copy_data)
    assert dst.get_data("annotation_data") == JSONLD


def test_paste_lcma_copy_into_plain_hierarchy_drops_annotation_data_without_crashing(
    lcma_tlui, lcma_form, hierarchy_tlui, hierarchy_ui
):
    src = lcma_tlui.get_element(lcma_form.id)
    src.set_data("annotation_data", JSONLD)
    src.set_data("label", "carried")
    copy_data = lcma_tlui.get_copy_data_from_hierarchy_ui(src)

    # The hierarchy unit has no annotation_data attribute; paste must skip it (not raise
    # SetComponentDataError) while still applying the shared attributes.
    assert not hasattr(hierarchy_ui.tl_component, "annotation_data")
    paste_into_element(hierarchy_ui, copy_data)
    assert hierarchy_ui.get_data("label") == "carried"
    assert not hasattr(hierarchy_ui.tl_component, "annotation_data")
