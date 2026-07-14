from __future__ import annotations

from typing import Any

from compneurovis.core.app_spec import AppRef, app_ref
from compneurovis.core.values import ValueBindingSpec


def resolve_binding(value, values: dict[Any, Any], fragment_id: str | None = None):
    if isinstance(value, ValueBindingSpec):
        if fragment_id is not None:
            scoped = app_ref(value.key, fragment_id=fragment_id)
            if scoped in values:
                return values.get(scoped)
        return values.get(value.key)
    if isinstance(value, AppRef):
        if value in values:
            return values.get(value)
        return values.get(value.id, value)
    return value
