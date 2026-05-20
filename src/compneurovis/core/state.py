from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StateBindingSpec:
    """Reference a value in an actor-local binding namespace."""

    key: str

