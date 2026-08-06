"""Small shared helpers for two-dimensional plot widgets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from compneurovis.core.values import ValueBindingSpec
from compneurovis.core.visual_contributions import VisualContributionSpec
from compneurovis.inline.refs import ControlRef, ValueRef, bind, binding_key


@dataclass(frozen=True, slots=True)
class LevelMarker:
    """Typed authoring declaration lowered to a neutral Plot2D contribution."""

    value: Any
    orientation: str = "horizontal"
    color: Any = "#d62728"
    width: float = 2.0
    label: str = ""


def level_items(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(
        value,
        (str, bytes, LevelMarker, ValueBindingSpec, ControlRef, ValueRef),
    ):
        return (value,)
    try:
        return tuple(value)
    except TypeError:
        return (value,)


def level_marker(item: Any, default_orientation: str) -> LevelMarker:
    if isinstance(item, LevelMarker):
        return item
    if isinstance(item, (ControlRef, ValueRef)):
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


def level_contributions(
    levels: tuple[LevelMarker, ...],
    *,
    view_id: str,
) -> tuple[VisualContributionSpec, ...]:
    return tuple(
        VisualContributionSpec(
            id=f"{view_id}_level_{index}",
            kind="level_marker",
            capability="plot2d.layers/v1",
            properties={
                "value": bind(marker.value),
                "orientation": marker.orientation,
                "color": bind(marker.color),
                "width": marker.width,
                "label": marker.label,
            },
        )
        for index, marker in enumerate(levels)
    )


__all__ = [
    "LevelMarker",
    "level_contributions",
    "level_items",
    "level_marker",
]
