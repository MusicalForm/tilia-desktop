from __future__ import annotations

from typing import TYPE_CHECKING

from tilia.timelines.base.validators import validate_string
from tilia.timelines.component_kinds import ComponentKind
from tilia.timelines.hierarchy.components import Hierarchy

if TYPE_CHECKING:
    from tilia.timelines.lcma.timeline import LcmaTimeline


class LcmaForm(Hierarchy):
    """A hierarchy unit that also carries an LCMA structured annotation.

    All of the nesting, timing and create-child / group / split / merge editing
    behaviour is inherited from :class:`Hierarchy` unchanged. The only addition
    is ``annotation_data``: an opaque JSON-LD string produced and consumed by
    the embedded LCMA annotation builder. It is stored verbatim and round-trips
    losslessly through the ``.tla`` file (it is just another serializable
    string; the model logic lives on the builder side, not here).
    """

    SERIALIZABLE = Hierarchy.SERIALIZABLE + ["annotation_data"]

    validators = {
        **Hierarchy.validators,
        "annotation_data": validate_string,
    }

    KIND = ComponentKind.LCMA_FORM

    def __init__(
        self,
        timeline: LcmaTimeline,
        id: int,
        start: float,
        end: float,
        level: int,
        annotation_data: str = "",
        **kwargs,
    ):
        self.annotation_data = annotation_data
        super().__init__(timeline, id, start, end, level, **kwargs)

    def __repr__(self):
        repr_ = f"LcmaForm({self.start}, {self.end}, {self.level}"
        try:
            if self.label:
                repr_ += f", {self.label}"
        except AttributeError:
            pass  # UI has not been created yet
        repr_ += ")"
        return repr_
