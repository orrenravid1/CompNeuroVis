from dataclasses import dataclass

from compneurovis.core.specs import SpecBase


@dataclass(frozen=True, slots=True)
class StateBindingSpec(SpecBase):
    """Reference a value in an actor-local binding namespace."""

    key: str

