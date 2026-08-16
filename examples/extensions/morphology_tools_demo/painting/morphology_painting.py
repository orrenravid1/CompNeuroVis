"""Reusable entity-level painting behavior for an existing morphology."""

from __future__ import annotations

from dataclasses import dataclass
import time
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
        stroke_started_at: float | None = None
        stroke_event_count = 0
        stroke_update_count = 0
        stroke_payload_bytes = 0
        stroke_set_data_ms = 0.0

        def paint(ctx, event) -> None:
            nonlocal last_entity_id, stroke_started_at, stroke_event_count
            nonlocal stroke_update_count, stroke_payload_bytes, stroke_set_data_ms
            if event.phase == "press":
                stroke_started_at = time.perf_counter()
                stroke_event_count = 0
                stroke_update_count = 0
                stroke_payload_bytes = 0
                stroke_set_data_ms = 0.0
            stroke_event_count += 1
            if event.phase in ("release", "cancel"):
                elapsed_ms = (
                    0.0
                    if stroke_started_at is None
                    else (time.perf_counter() - stroke_started_at) * 1000.0
                )
                print(
                    "[morphology-paint] stroke",
                    f"phase={event.phase}",
                    f"events={stroke_event_count}",
                    f"updates={stroke_update_count}",
                    f"payload_bytes={stroke_payload_bytes}",
                    f"set_data_ms={stroke_set_data_ms:.3f}",
                    f"elapsed_ms={elapsed_ms:.3f}",
                    flush=True,
                )
                last_entity_id = None
                stroke_started_at = None
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
            submit_started_at = time.perf_counter()
            ctx.set_data(color, values.copy())
            stroke_set_data_ms += (
                time.perf_counter() - submit_started_at
            ) * 1000.0
            stroke_update_count += 1
            stroke_payload_bytes += values.nbytes
            last_entity_id = entity_id

        context.on_entity_pointer(pointer, paint)
        return color


__all__ = ["MorphologyPainting"]
