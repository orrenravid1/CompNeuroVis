from __future__ import annotations

from typing import Any

from compneurovis.core.state import StateBindingSpec


def resolve_binding(value, state: dict[str, Any]):
    if isinstance(value, StateBindingSpec):
        return state.get(value.key)
    return value
