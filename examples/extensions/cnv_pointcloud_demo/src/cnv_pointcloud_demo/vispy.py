from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

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
    kind: ClassVar[str] = VIEW_KIND
    id: str
    title: Any
    geometry_id: str
    values_id: str
    selection_id: str = ""
    point_size: float = 8.0
    color: Any = (0.15, 0.45, 0.85, 1.0)
    background_color: Any = "white"
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
            selection_id=view.selections.get("entities", ""),
            max_refresh_hz=view.max_refresh_hz,
            **dict(view.properties),
        )


class PointCloudVisual:
    def __init__(self, view, *, panel_id: str | None = None) -> None:
        del panel_id
        self._markers = scene.visuals.Markers(parent=view.scene)
        self._markers.visible = False
        self._positions = np.empty((0, 3), dtype=np.float32)
        self._entity_ids: tuple[str, ...] = ()
        self._colors = np.empty((0, 4), dtype=np.float32)
        self._point_size = 8.0

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
        entity_ids = tuple(str(value) for value in geometry.data["entity_ids"])
        field = ctx.field(view.values_id)
        colors = _point_colors(
            None if field is None else field.values,
            count=len(positions),
            fallback=view.color,
        )
        selected = (
            ctx.values.get(
                cnv.AppRef(view.selection_id, fragment_id=ctx.fragment_id),
                (),
            )
            if view.selection_id
            else ()
        )
        selected_ids = {str(value) for value in selected or ()}
        for index, entity_id in enumerate(entity_ids):
            if entity_id in selected_ids:
                colors[index] = (1.0, 0.75, 0.05, 1.0)
        self._positions = positions
        self._entity_ids = entity_ids
        self._colors = colors
        self._point_size = float(view.point_size)
        self._markers.set_data(
            pos=positions,
            face_color=colors,
            edge_width=0.0,
            size=self._point_size,
        )
        self._markers.visible = True

    def pick_entity(self, xf: int, yf: int, canvas) -> str | None:
        if not self._entity_ids:
            return None
        ids = np.arange(1, len(self._entity_ids) + 1, dtype=np.uint32)
        id_colors = np.stack(
            (
                (ids & 0xFF) / 255.0,
                ((ids >> 8) & 0xFF) / 255.0,
                ((ids >> 16) & 0xFF) / 255.0,
                np.ones_like(ids),
            ),
            axis=1,
        ).astype(np.float32)
        self._markers.set_data(
            pos=self._positions,
            face_color=id_colors,
            edge_width=0.0,
            size=self._point_size,
        )
        try:
            image = canvas.render(region=(xf, yf, 1, 1), size=(1, 1), alpha=False)
        finally:
            self._markers.set_data(
                pos=self._positions,
                face_color=self._colors,
                edge_width=0.0,
                size=self._point_size,
            )
        pixel = np.asarray(image)[0, 0, :3]
        if pixel.dtype != np.uint8:
            pixel = np.round(pixel * 255).astype(np.uint8)
        color_id = int(pixel[0]) | (int(pixel[1]) << 8) | (int(pixel[2]) << 16)
        index = color_id - 1
        if index < 0 or index >= len(self._entity_ids):
            return None
        return self._entity_ids[index]

    def wants_selection(self, view: PointCloudViewConfig) -> bool:
        return bool(view.selection_id)


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
