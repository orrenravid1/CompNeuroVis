"""Vispy presentations for the app-local morphology tool contributions."""

from __future__ import annotations

import numpy as np
from vispy import scene
from vispy.color import Color

from compneurovis.frontends.vispy import register_scene_contribution

from morphology_tools import CHANNEL_LAYER_KIND, MARKER_LAYER_KIND


class ChannelLayerRenderer:
    def __init__(self, context, spec) -> None:
        del spec
        self._markers = scene.visuals.Markers(parent=context.surface.scene)
        self._markers.visible = False

    def clear(self) -> None:
        self._markers.visible = False

    def refresh(self, spec, inputs, geometries, selections, properties, values):
        del spec, selections, values
        geometry = geometries.get("morphology")
        field = inputs.get("values")
        if geometry is None or field is None:
            return self.clear()
        positions = np.asarray(geometry.data["positions"], dtype=np.float32)
        magnitudes = np.asarray(field.values, dtype=np.float32).reshape(-1)
        if len(positions) != len(magnitudes):
            raise ValueError("Morphology channel values must match entity count")
        finite = np.isfinite(magnitudes)
        normalized = np.zeros_like(magnitudes)
        if np.any(finite):
            low = float(np.min(magnitudes[finite]))
            high = float(np.max(magnitudes[finite]))
            normalized[finite] = (
                1.0 if abs(high - low) < 1e-12
                else (magnitudes[finite] - low) / (high - low)
            )
        rgba = np.asarray(Color(properties.get("color", "#00a6ff")).rgba)
        colors = np.tile(rgba, (len(positions), 1)).astype(np.float32)
        colors[:, 3] *= 0.15 + 0.85 * normalized
        offset = np.asarray(properties.get("offset", (0.0, 0.0, 0.0)), dtype=np.float32)
        self._markers.set_data(
            pos=positions + offset,
            face_color=colors,
            edge_width=0.0,
            size=float(properties.get("size", 10.0)),
        )
        self._markers.visible = True


class MarkerLayerRenderer:
    def __init__(self, context, spec) -> None:
        del spec
        self._markers = scene.visuals.Markers(parent=context.surface.scene)
        self._markers.visible = False

    def clear(self) -> None:
        self._markers.visible = False

    def refresh(self, spec, inputs, geometries, selections, properties, values):
        del spec, geometries, selections, properties, values
        field = inputs.get("markers")
        rows = (
            np.empty((0, 8), dtype=np.float32)
            if field is None
            else np.asarray(field.values, dtype=np.float32)
        )
        if not len(rows):
            return self.clear()
        if rows.ndim != 2 or rows.shape[1] != 8:
            raise ValueError("Marker table must have eight attributes")
        self._markers.set_data(
            pos=rows[:, :3],
            face_color=rows[:, 3:7],
            edge_color="white",
            edge_width=1.0,
            size=rows[:, 7],
        )
        self._markers.visible = True


def register() -> None:
    register_scene_contribution(
        CHANNEL_LAYER_KIND,
        lambda context, spec: ChannelLayerRenderer(context, spec),
    )
    register_scene_contribution(
        MARKER_LAYER_KIND,
        lambda context, spec: MarkerLayerRenderer(context, spec),
    )


__all__ = ["register"]
