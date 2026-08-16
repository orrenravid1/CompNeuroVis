"""App-local spherical morphology brush authored through public seams."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from compneurovis.frontends.vispy import register_vispy_plugin
from compneurovis.geometries import MorphologyGeometry
from compneurovis.widgets import DataRef, MorphologyRef, Widget


register_vispy_plugin("sphere_brush_vispy:register")

SPHERE_BRUSH_PREVIEW_KIND = "demo_sphere_brush_preview"
SCENE_CAPABILITY = "scene3d.layers/v1"


def _segments_intersecting_sphere(
    geometry: MorphologyGeometry,
    center: np.ndarray,
    radius: float,
) -> np.ndarray:
    """Vectorized exact distance test against finite capped cylinders."""
    axes = np.asarray(geometry.orientations[:, :, 2], dtype=np.float64)
    axis_lengths = np.linalg.norm(axes, axis=1)
    axes = axes / np.where(axis_lengths > 1e-12, axis_lengths, 1.0)[:, None]
    delta = np.asarray(center, dtype=np.float64)[None, :] - geometry.positions
    axial_signed = np.einsum("ij,ij->i", delta, axes)
    radial_vector = delta - axial_signed[:, None] * axes
    radial = np.linalg.norm(radial_vector, axis=1)
    outside_axial = np.maximum(
        np.abs(axial_signed) - np.asarray(geometry.lengths) * 0.5,
        0.0,
    )
    outside_radial = np.maximum(
        radial - np.asarray(geometry.radii),
        0.0,
    )
    return np.hypot(outside_axial, outside_radial) <= float(radius)


@dataclass(frozen=True, slots=True)
class MorphologySphereBrush(Widget[DataRef]):
    morphology: MorphologyRef
    geometry: MorphologyGeometry
    initial_values: Any
    brush_value: Any
    brush_radius: Any
    enabled: Any
    preview_color: tuple[float, float, float, float] = (1.0, 0.35, 0.05, 0.3)

    def declare(self, context) -> DataRef:
        color = self.morphology.color
        if color is None:
            raise ValueError("MorphologySphereBrush requires morphology color data")

        values = np.asarray(self.initial_values, dtype=np.float32).reshape(-1).copy()
        if values.shape != (len(self.geometry.entity_ids),):
            raise ValueError("Initial brush values must match morphology entities")

        hit_target = context.hit_target("sphere brush overlap")
        context.visual_contribution(
            SPHERE_BRUSH_PREVIEW_KIND,
            "Sphere brush preview",
            target=self.morphology,
            capability=SCENE_CAPABILITY,
            geometries={"morphology": self.morphology.geometry},
            hit_targets={"sphere_brush": hit_target},
            properties={
                "enabled": self.enabled,
                "radius": self.brush_radius,
                "color": self.preview_color,
            },
        )
        pointer = context.pointer(
            "sphere brush gesture",
            hit_target=hit_target,
            result_kind="hit",
            enabled=self.enabled,
        )

        def apply_brush(ctx, event) -> None:
            if event.phase not in ("press", "move") or event.value is None:
                return
            world_position = getattr(event.value, "world_position", None)
            if world_position is None:
                return
            center = np.asarray(world_position, dtype=np.float64)
            radius = float(ctx.get_value(self.brush_radius))
            affected = _segments_intersecting_sphere(
                self.geometry,
                center,
                radius,
            )
            values[affected] = float(ctx.get_value(self.brush_value))
            ctx.set_data(color, values.copy())

        context.on_pointer(pointer, apply_brush)
        return color


__all__ = ["MorphologySphereBrush", "SPHERE_BRUSH_PREVIEW_KIND"]
