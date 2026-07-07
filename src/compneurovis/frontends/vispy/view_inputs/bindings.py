from __future__ import annotations

from typing import Any

from compneurovis.core.app_spec import AppRef, app_ref
from compneurovis.core.state import StateBindingSpec


def resolve_binding(value, state: dict[Any, Any], fragment_id: str | None = None):
    if isinstance(value, StateBindingSpec):
        if fragment_id is not None:
            scoped = app_ref(value.key, fragment_id=fragment_id)
            if scoped in state:
                return state.get(scoped)
        return state.get(value.key)
    if isinstance(value, AppRef):
        if value in state:
            return state.get(value)
        return state.get(value.id, value)
    return value
