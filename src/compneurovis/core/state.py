from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StateBindingSpec:
    """Resolve a view or control value from frontend-owned state."""

    key: str

