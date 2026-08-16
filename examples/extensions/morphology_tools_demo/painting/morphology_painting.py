"""Reusable entity-level painting behavior for an existing morphology."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from compneurovis.widgets import DataRef, MorphologyRef, Widget


@dataclass(frozen=True, slots=True)
class MorphologyPainting(Widget[DataRef]):
    """Paint scalar values into a morphology's existing color field.

    The widget owns behavior only. It does not create a panel or register a
    renderer: the target morphology already owns presentation of its color data.
    """

    morphology: MorphologyRef
    entity_ids: Sequence[str]
    initial_values: Any
    brush_value: Any
    enabled: Any

    def declare(self, context) -> DataRef:
        color = self.morphology.color
        click = self.morphology.entity_click
        if color is None:
            raise ValueError(
                "MorphologyPainting requires a morphology with values=... or color=..."
            )
        if click is None:
            raise ValueError("MorphologyPainting requires a clickable morphology")

        entity_ids = tuple(str(value) for value in self.entity_ids)
        values = np.asarray(self.initial_values, dtype=np.float32).reshape(-1).copy()
        if values.shape != (len(entity_ids),):
            raise ValueError(
                "MorphologyPainting initial_values must match the entity count"
            )

        pointer = context.entity_pointer(
            "paint gesture",
            interaction=click,
            enabled=self.enabled,
        )
        last_entity_id: str | None = None

        def paint(ctx, event) -> None:
            nonlocal last_entity_id
            if event.phase in ("release", "cancel"):
                last_entity_id = None
                return
            entity_id = event.value
            if entity_id is None:
                last_entity_id = None
                return
            if entity_id == last_entity_id:
                return
            info = ctx.entity_info(entity_id)
            if info is None:
                return
            index = int(info["index"])
            if index < 0 or index >= len(values):
                raise IndexError(
                    f"Entity index {index} is outside the paint field"
                )
            brush = float(ctx.get_value(self.brush_value))
            values[index] = brush
            ctx.set_data(color, values.copy())
            last_entity_id = entity_id

        context.on_entity_pointer(pointer, paint)
        return color


__all__ = ["MorphologyPainting"]
