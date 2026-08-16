"""Vispy preview for the app-local spherical morphology brush."""

from __future__ import annotations

import numpy as np
from vispy import scene
from vispy.visuals.transforms import STTransform

from compneurovis.core import HitRecord
from compneurovis.geometries.morphology import morphology_geometry_from_spec
from compneurovis.frontends.vispy import register_scene_contribution

from sphere_brush import (
    SPHERE_BRUSH_PREVIEW_KIND,
    _segments_intersecting_sphere,
)


class SphereBrushPreviewRenderer:
    def __init__(self, context, spec) -> None:
        del spec
        self._hub = context.pointer_observations
        if self._hub is None:
            raise RuntimeError("This Scene3D host does not expose pointer observations")
        self._sphere = scene.visuals.Sphere(
            radius=1.0,
            rows=18,
            cols=24,
            method="latitude",
            color=(1.0, 0.35, 0.05, 0.3),
            edge_color=(1.0, 0.65, 0.1, 1.0),
            shading=None,
            parent=context.surface.scene,
        )
        self._sphere.mesh.set_gl_state("translucent")
        self._sphere.visible = False
        self._unsubscribe = None
        self._geometry = None
        self._radius = 1.0
        self._color = (1.0, 0.35, 0.05, 0.3)
        self._reported_visible = False

    def _observe(self) -> None:
        if self._unsubscribe is None:
            self._unsubscribe = self._hub.subscribe(
                lambda _event: None,
                needs_hits=True,
            )

    def _stop_observing(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def hit_test(self, xf, yf, canvas):
        if self._geometry is None:
            self._sphere.visible = False
            return None
        origin, direction = self._canvas_ray(xf, yf, canvas)
        positions = np.asarray(self._geometry.positions, dtype=np.float64)
        offsets = positions - origin[None, :]
        depths = offsets @ direction
        forward = depths >= 0.0
        if not np.any(forward):
            self._sphere.visible = False
            return None
        radial_squared = np.einsum("ij,ij->i", offsets, offsets) - depths * depths
        radial_squared[~forward] = np.inf
        anchor_index = int(np.argmin(radial_squared))
        center = origin + depths[anchor_index] * direction
        self._sphere.transform = STTransform(
            scale=(self._radius, self._radius, self._radius),
            translate=tuple(float(value) for value in center),
        )
        self._sphere.visible = True
        self._sphere.update()
        if not self._reported_visible:
            print(
                "[sphere-brush-preview] visible",
                f"center={tuple(round(float(value), 3) for value in center)}",
                f"radius={self._radius:.3f}",
                flush=True,
            )
            self._reported_visible = True
        affected = _segments_intersecting_sphere(
            self._geometry,
            center,
            self._radius,
        )
        if not np.any(affected):
            return None
        return HitRecord(
            target_role="sphere_brush",
            primitive_id="sphere-overlap",
            world_position=tuple(float(value) for value in center),
        )

    def _canvas_ray(self, xf, yf, canvas):
        pixel_scale = max(float(canvas.pixel_scale), 1e-12)
        x = float(xf) / pixel_scale
        y = float(canvas.size[1]) - float(yf) / pixel_scale - 1.0
        transform = self._sphere.parent.node_transform(canvas.scene)

        def unproject(z):
            point = np.asarray(
                transform.imap((x, y, z, 1.0)),
                dtype=np.float64,
            )
            if point.shape[-1] == 4:
                point = point[:3] / point[3]
            return point[:3]

        origin = unproject(-1.0)
        far = unproject(1.0)
        direction = far - origin
        direction /= np.linalg.norm(direction)
        return origin, direction

    def clear(self) -> None:
        self._stop_observing()
        self._sphere.visible = False

    def refresh(self, spec, inputs, geometries, selections, properties, values):
        del spec, inputs, selections, values
        geometry = geometries.get("morphology")
        enabled = bool(properties.get("enabled", False))
        if geometry is None or not enabled:
            return self.clear()
        self._geometry = morphology_geometry_from_spec(geometry)
        if self._geometry is None:
            raise ValueError("Sphere brush requires morphology geometry")
        self._radius = max(float(properties.get("radius", 1.0)), 0.0)
        self._color = tuple(float(value) for value in properties.get("color"))
        self._sphere.mesh.color = self._color
        self._sphere.visible = False
        self._reported_visible = False
        self._observe()


def register() -> None:
    register_scene_contribution(
        SPHERE_BRUSH_PREVIEW_KIND,
        lambda context, spec: SphereBrushPreviewRenderer(context, spec),
    )


__all__ = ["register"]
