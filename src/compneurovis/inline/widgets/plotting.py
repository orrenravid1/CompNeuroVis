"""Small shared helpers for two-dimensional plot widgets."""

from __future__ import annotations

from typing import Any

from compneurovis.core.values import ValueBindingSpec
from compneurovis.core.views import LevelMarker
from compneurovis.inline.handles import ControlHandle, ValueRef, binding_key


def level_items(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(
        value,
        (str, bytes, LevelMarker, ValueBindingSpec, ControlHandle, ValueRef),
    ):
        return (value,)
    try:
        return tuple(value)
    except TypeError:
        return (value,)


def level_marker(item: Any, default_orientation: str) -> LevelMarker:
    if isinstance(item, LevelMarker):
        return item
    if isinstance(item, (ControlHandle, ValueRef)):
        return LevelMarker(
            value=ValueBindingSpec(binding_key(item)),
            orientation=default_orientation,
        )
    if isinstance(item, str):
        return LevelMarker(
            value=ValueBindingSpec(item),
            orientation=default_orientation,
        )
    if isinstance(item, ValueBindingSpec):
        return LevelMarker(value=item, orientation=default_orientation)
    return LevelMarker(value=float(item), orientation=default_orientation)


__all__ = ["level_items", "level_marker"]
