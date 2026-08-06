from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from vispy import scene

import compneurovis as cnv
from compneurovis.frontends.vispy import (
    register_3d_visual,
    register_view_refresh_schema,
    register_view_render_config,
)

from cnv_pointcloud_demo.authoring import GEOMETRY_KIND, VIEW_KIND


@dataclass(frozen=True, slots=True)
class PointCloudViewConfig:
    id: str
    title: Any
    geometry_id: str
    values_id: str
    point_size: float = 8.0
    color: Any = (0.15, 0.45, 0.85, 1.0)
    camera_distance: float | None = 20.0
    camera_elevation: float = 30.0
    camera_azimuth: float = 30.0
    max_refresh_hz: float | None = None

    @classmethod
    def from_extension(
        cls,
        view: cnv.ExtensionViewSpec,
    ) -> "PointCloudViewConfig":
        return cls(
            id=view.id,
            title=view.title,
            geometry_id=view.geometries.get("points", ""),
            values_id=view.inputs.get("values", ""),
            max_refresh_hz=view.max_refresh_hz,
            **dict(view.properties),
        )


class PointCloudVisual:
    def __init__(self, view, *, panel_id: str | None = None) -> None:
        del panel_id
        self._markers = scene.visuals.Markers(parent=view.scene)
        self._markers.visible = False

    def clear(self) -> None:
        self._markers.visible = False

    def refresh_for_target(
        self,
        kind: str,
        view: PointCloudViewConfig,
        ctx,
    ) -> None:
        if kind != VIEW_KIND:
            return
        geometry = ctx.app_spec.geometry(
            cnv.AppRef(view.geometry_id, fragment_id=ctx.fragment_id)
        )
        if (
            not isinstance(geometry, cnv.ExtensionGeometrySpec)
            or geometry.kind != GEOMETRY_KIND
        ):
            self.clear()
            return
        positions = np.asarray(geometry.data["positions"], dtype=np.float32)
        field = ctx.field(view.values_id)
        colors = _point_colors(
            None if field is None else field.values,
            count=len(positions),
            fallback=view.color,
        )
        self._markers.set_data(
            pos=positions,
            face_color=colors,
            edge_width=0.0,
            size=float(view.point_size),
        )
        self._markers.visible = True

    def pick_entity(self, xf: int, yf: int, canvas) -> str | None:
        del xf, yf, canvas
        return None


def _point_colors(values, *, count: int, fallback: Any) -> np.ndarray:
    if values is None:
        color = np.asarray(fallback, dtype=np.float32)
        return np.repeat(color.reshape(1, 4), count, axis=0)
    scalars = np.asarray(values, dtype=np.float32).reshape(-1)
    if len(scalars) != count:
        raise ValueError("Point-cloud scalar values must match the point count")
    low = float(np.nanmin(scalars)) if scalars.size else 0.0
    high = float(np.nanmax(scalars)) if scalars.size else 1.0
    span = high - low
    normalized = (
        np.zeros_like(scalars)
        if not np.isfinite(span) or span <= 0.0
        else np.clip((scalars - low) / span, 0.0, 1.0)
    )
    return np.stack(
        (
            normalized,
            np.full_like(normalized, 0.2),
            1.0 - normalized,
            np.ones_like(normalized),
        ),
        axis=1,
    )


def register() -> None:
    register_view_render_config(VIEW_KIND, PointCloudViewConfig.from_extension)
    register_view_refresh_schema(
        VIEW_KIND,
        patch={VIEW_KIND: None},
        full_refresh=(VIEW_KIND,),
        field_id_props={"values_id": VIEW_KIND},
    )
    register_3d_visual(
        VIEW_KIND,
        PointCloudVisual,
        targets=(VIEW_KIND,),
    )


__all__ = ["PointCloudViewConfig", "PointCloudVisual", "register"]
