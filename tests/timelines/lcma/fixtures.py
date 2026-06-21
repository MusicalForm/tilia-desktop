import functools

import pytest

from tilia.requests import Post, post
from tilia.timelines.component_kinds import ComponentKind
from tilia.timelines.lcma.timeline import LcmaTimeline


@pytest.fixture
def lcma_tlui(lcma_tl, tluis):
    post(Post.APP_STATE_RECORD, "tlui fixture")
    ui = tluis.get_timeline_ui(lcma_tl.id)
    ui.create_lcma_form = lcma_tl.create_lcma_form
    ui.create_component = lcma_tl.create_component
    return ui  # will be deleted by tls


@pytest.fixture
def lcma_tl(tls):
    tl: LcmaTimeline = tls.create_timeline(LcmaTimeline)
    # drop the auto-created initial unit so tests start from empty
    tl.clear()
    tl.create_lcma_form = functools.partial(
        tl.create_component, ComponentKind.LCMA_FORM
    )
    return tl


@pytest.fixture
def lcma_form(lcma_tl):
    return lcma_tl.create_lcma_form(0, 1, 1)[0]


@pytest.fixture
def lcma_form_ui(lcma_tlui, lcma_form):
    return lcma_tlui.get_element(lcma_form.id)
