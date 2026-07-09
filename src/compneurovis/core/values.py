from dataclasses import dataclass

from compneurovis.core.specs import SpecBase


@dataclass(frozen=True, slots=True)
class ValueBindingSpec(SpecBase):
    """Reference a value in an actor-local binding namespace."""

    key: str

