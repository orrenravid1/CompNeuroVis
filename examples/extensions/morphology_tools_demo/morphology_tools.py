"""App-local morphology layers and tools using only public authoring seams."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

import numpy as np

from compneurovis.frontends.vispy import register_vispy_plugin
from compneurovis.widgets import DataRef, MorphologyRef, Widget


register_vispy_plugin("morphology_tools_vispy:register")

CHANNEL_LAYER_KIND = "demo_morphology_channel"
MARKER_LAYER_KIND = "demo_morphology_markers"
SCENE_CAPABILITY = "scene3d.layers/v1"


@dataclass(frozen=True, slots=True)
class MorphologyChannel(Widget[DataRef]):
    """One independently colored per-entity layer over a morphology."""

    morphology: MorphologyRef
    name: str
    entity_ids: Sequence[str]
    values: Any = None
    read: Callable[[], Any] | None = None
    source: DataRef | None = None
    color: str = "#00a6ff"
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    size: float = 10.0

    def declare(self, context) -> DataRef:
        supplied = sum(
            value is not None for value in (self.values, self.read, self.source)
        )
        if supplied != 1:
            raise ValueError(
                "MorphologyChannel requires exactly one of values, read, or source"
            )
        if self.source is not None:
            data = context.data(f"{self.name} values", source=self.source)
        elif self.read is not None:
            data = context.data(
                f"{self.name} values",
                read=self.read,
                labels=self.entity_ids,
            )
        else:
            data = context.data(
                f"{self.name} values",
                values=self.values,
                labels=self.entity_ids,
            )
        context.visual_contribution(
            CHANNEL_LAYER_KIND,
            self.name,
            target=self.morphology,
            capability=SCENE_CAPABILITY,
            inputs={"values": data},
            geometries={"morphology": self.morphology.geometry},
            properties={
                "color": self.color,
                "offset": self.offset,
                "size": self.size,
            },
        )
        return data


@dataclass(frozen=True, slots=True)
class MorphologyToolsRef:
    weights: DataRef
    markers: DataRef


@dataclass(frozen=True, slots=True)
class MorphologyTools(Widget[MorphologyToolsRef]):
    """Mode-routed paint and marker behavior over an existing morphology."""

    morphology: MorphologyRef
    entity_ids: Sequence[str]
    mode: Any
    weight: Any
    marker_color: Any

    def declare(self, context) -> MorphologyToolsRef:
        if self.morphology.entity_click is None:
            raise ValueError("MorphologyTools requires a clickable morphology")
        entity_ids = tuple(str(value) for value in self.entity_ids)
        weights_state = np.zeros(len(entity_ids), dtype=np.float32)
        marker_rows: list[list[float]] = []
        marker_columns = ("x", "y", "z", "r", "g", "b", "a", "size")
        colors = {
            "red": (1.0, 0.15, 0.1, 1.0),
            "green": (0.1, 0.8, 0.25, 1.0),
            "gold": (1.0, 0.7, 0.05, 1.0),
            "purple": (0.65, 0.25, 1.0, 1.0),
        }

        weights = context.data(
            "paint weights",
            values=weights_state,
            labels=entity_ids,
        )
        markers = context.snapshot(
            "markers",
            dims=("marker", "attribute"),
            coords={"marker": (), "attribute": marker_columns},
            values=np.empty((0, len(marker_columns)), dtype=np.float32),
        )
        context.visual_contribution(
            CHANNEL_LAYER_KIND,
            "Paint weights",
            target=self.morphology,
            capability=SCENE_CAPABILITY,
            inputs={"values": weights},
            geometries={"morphology": self.morphology.geometry},
            properties={
                "color": "#ff7b00",
                "offset": (0.0, 0.0, 1.0),
                "size": 13.0,
            },
        )
        context.visual_contribution(
            MARKER_LAYER_KIND,
            "Placed markers",
            target=self.morphology,
            capability=SCENE_CAPABILITY,
            inputs={"markers": markers},
            geometries={"morphology": self.morphology.geometry},
        )

        def handle_click(ctx, entity_id: str) -> bool:
            mode = str(ctx.get_value(self.mode))
            info = ctx.entity_info(entity_id)
            if info is None:
                return False
            if mode == "paint":
                weights_state[int(info["index"])] = float(
                    ctx.get_value(self.weight)
                )
                ctx.set_data(weights, weights_state.copy())
                return True
            if mode == "mark":
                position = tuple(float(value) for value in info["position"])
                color = colors[str(ctx.get_value(self.marker_color))]
                marker_rows.append([*position, *color, 16.0])
                ctx.set_data(
                    markers,
                    np.asarray(marker_rows, dtype=np.float32),
                    coords={
                        "marker": tuple(
                            f"marker-{index}" for index in range(len(marker_rows))
                        ),
                        "attribute": marker_columns,
                    },
                )
                return True
            return False

        context.on_entity_click(self.morphology.entity_click, handle_click)
        return MorphologyToolsRef(weights=weights, markers=markers)


__all__ = [
    "CHANNEL_LAYER_KIND",
    "MARKER_LAYER_KIND",
    "MorphologyChannel",
    "MorphologyTools",
    "MorphologyToolsRef",
]
