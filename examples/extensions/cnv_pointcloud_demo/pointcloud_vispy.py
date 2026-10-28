from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

import numpy as np
import pyqtgraph as pg
from PyQt6 import QtWidgets
from vispy import scene
from vispy.color import Color
from vispy.visuals.transforms import STTransform

import compneurovis as cnv
from compneurovis.frontends.vispy import (
    register_scene_contribution,
    register_scene_layer,
    register_operator_adapter,
    register_renderer,
)

from pointcloud import (
    GEOMETRY_KIND,
    SCATTER_VIEW_KIND,
    VIEW_KIND,
)
from pointcloud_slice import (
    PointCloudSliceConfig,
    SLICE_FIELD_SCHEMA,
    SLICE_OPERATOR_KIND,
    SLICE_OVERLAY_KIND,
    _contains_binding,
    field_from_point_cloud_slice,
)


@dataclass(frozen=True, slots=True)
class PointCloudViewConfig:
    kind: ClassVar[str] = VIEW_KIND
    id: str
    title: Any
    geometry_id: str
    values_id: str
    selection_id: str = ""
    hit_target_id: str = ""
    point_size: float = 8.0
    color: Any = (0.15, 0.45, 0.85, 1.0)
    background_color: Any = "white"
    camera_distance: float | None = 20.0
    camera_elevation: float = 30.0
    camera_azimuth: float = 30.0
    max_refresh_hz: float | None = None

    @classmethod
    def from_view(
        cls,
        view: cnv.ViewSpec,
    ) -> "PointCloudViewConfig":
        return cls(
            id=view.id,
            title=view.title,
            geometry_id=view.geometries.get("points", ""),
            values_id=view.inputs.get("values", ""),
            selection_id=view.selections.get("entities", ""),
            hit_target_id=view.hit_targets.get("entities", ""),
            max_refresh_hz=view.max_refresh_hz,
            **dict(view.properties),
        )


class PointCloudVisual:
    def __init__(self, view, *, panel_id: str | None = None) -> None:
        self._scene = view.scene
        self._panel_id = panel_id
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
            not isinstance(geometry, cnv.GeometrySpec)
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

    def hit_test(self, xf: int, yf: int, canvas) -> cnv.HitRecord | None:
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
        return cnv.HitRecord(
            target_role="entities",
            primitive_id=index,
        )

    def value_for_hit(self, hit: cnv.HitRecord, result_kind: str) -> str | None:
        if result_kind != "entity":
            raise ValueError(
                f"Point-cloud visual cannot resolve click result {result_kind!r}"
            )
        index = hit.primitive_id
        if not isinstance(index, int) or index < 0 or index >= len(self._entity_ids):
            return None
        return self._entity_ids[index]

    def wants_hit_test(self, view: PointCloudViewConfig) -> bool:
        return bool(view.hit_target_id)


class PointCloudPlaneSliceRenderer:
    """PlaneSlice-owned Scene3D slab; PointCloudVisual knows nothing about it."""

    def __init__(self, context, spec) -> None:
        del spec
        self._scene = context.surface.scene
        self._planes: list[Any] = []

    def clear(self) -> None:
        for plane in self._planes:
            plane.parent = None
        self._planes.clear()

    def refresh(
        self, spec, inputs, geometries, selections, properties, values
    ) -> None:
        del spec, selections, values
        self.clear()
        geometry = geometries.get("points")
        sliced_field = inputs.get("slice")
        if (
            not isinstance(geometry, cnv.GeometrySpec)
            or geometry.kind != GEOMETRY_KIND
            or sliced_field is None
        ):
            return
        positions = np.asarray(geometry.data["positions"], dtype=np.float32)
        if positions.ndim != 2 or positions.shape[1] != 3 or not len(positions):
            return
        axis = str(sliced_field.attrs.get("slice_axis", "z"))
        if axis not in ("x", "y", "z"):
            return
        axis_index = ("x", "y", "z").index(axis)
        center_value = float(sliced_field.attrs.get("slice_center", 0.0))
        half_width = float(sliced_field.attrs.get("slice_half_width", 0.0))
        bounds_min = np.min(positions, axis=0)
        bounds_max = np.max(positions, axis=0)
        rgba = np.asarray(
            Color(properties.get("color", "#ffb000")).rgba,
            dtype=np.float32,
        )
        fill = rgba.copy()
        fill[3] = float(
            np.clip(float(properties.get("alpha", 0.18)), 0.0, 1.0)
        )
        edge = rgba.copy()
        edge[3] = min(1.0, max(0.45, fill[3] * 4.0))
        other_indices = tuple(index for index in range(3) if index != axis_index)
        width = max(
            float(
                bounds_max[other_indices[0]]
                - bounds_min[other_indices[0]]
            ),
            1e-6,
        )
        height = max(
            float(
                bounds_max[other_indices[1]]
                - bounds_min[other_indices[1]]
            ),
            1e-6,
        )
        for coordinate in sorted(
            {center_value - half_width, center_value + half_width}
        ):
            center = 0.5 * (bounds_min + bounds_max)
            center[axis_index] = coordinate
            plane = scene.visuals.Plane(
                width=width,
                height=height,
                direction=f"+{axis}",
                color=tuple(fill),
                edge_color=tuple(edge),
                parent=self._scene,
            )
            plane.transform = STTransform(translate=tuple(center))
            self._planes.append(plane)


class Scatter2DHost(QtWidgets.QGroupBox):
    """App-local Qt/pyqtgraph host for projected point data."""

    def __init__(
        self,
        *,
        panel_id: str,
        view_id: str | cnv.AppRef,
        title: str,
        parent=None,
    ) -> None:
        super().__init__(title, parent)
        self.panel_id = panel_id
        self.view_id = view_id
        self._plot = pg.PlotWidget()
        self._scatter = pg.ScatterPlotItem()
        self._plot.addItem(self._scatter)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.addWidget(self._plot)

    def refresh(
        self,
        view: cnv.ViewSpec,
        inputs,
        properties,
        values,
    ) -> None:
        del view, values
        field = inputs.get("data")
        if field is None:
            self._scatter.clear()
            return
        if field.attrs.get("schema") != SLICE_FIELD_SCHEMA:
            raise ValueError(f"Scatter2D requires field schema {SLICE_FIELD_SCHEMA!r}")
        columns = np.asarray(field.values, dtype=np.float32)
        if columns.ndim != 2 or columns.shape[1] != 3:
            raise ValueError("Scatter2D data must have u, v, and value columns")
        colors = _point_colors(
            columns[:, 2],
            count=len(columns),
            fallback=properties.get("color", (0.15, 0.45, 0.85, 1.0)),
        )
        brushes = [
            pg.mkBrush(*(np.clip(color, 0.0, 1.0) * 255).astype(np.uint8))
            for color in colors
        ]
        self._scatter.setData(
            x=columns[:, 0],
            y=columns[:, 1],
            pen=None,
            brush=brushes,
            size=float(properties.get("point_size", 9.0)),
        )
        self._plot.setBackground(properties.get("background_color", "white"))
        self._plot.setLabel("bottom", str(field.attrs.get("u_axis", "u")))
        self._plot.setLabel("left", str(field.attrs.get("v_axis", "v")))
        if len(columns):
            self._plot.enableAutoRange()


class _PointCloudSliceAdapter:
    _COMPUTE_PROPERTIES = frozenset(
        {"inputs", "geometries", "axis", "position", "thickness"}
    )

    @staticmethod
    def _config(operator) -> PointCloudSliceConfig:
        return PointCloudSliceConfig.from_view(operator)

    def affects_output(self, changed_props) -> bool:
        return bool(changed_props & self._COMPUTE_PROPERTIES)

    def output_field_deps(self, op, fragment_id) -> tuple:
        del fragment_id
        return (self._config(op).values_id,)

    def output_binds_value(self, op, value_key, fragment_id) -> bool:
        config = self._config(op)
        return any(
            _contains_binding(value, value_key, fragment_id)
            for value in (config.axis, config.position, config.thickness)
        )

    def resolve_field(self, op, ctx) -> cnv.Field | None:
        config = self._config(op)
        geometry = ctx.geometry(config.geometry_id)
        values_field = ctx.field(config.values_id)
        if geometry is None or values_field is None:
            return None
        if not isinstance(geometry, cnv.GeometrySpec):
            raise TypeError("Point-cloud slice geometry must be a GeometrySpec")
        return field_from_point_cloud_slice(
            geometry,
            values_field,
            config.resolved(ctx.values, ctx.fragment_id),
        )


_SLICE_ADAPTER = _PointCloudSliceAdapter()


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
    register_operator_adapter(SLICE_OPERATOR_KIND, _SLICE_ADAPTER)
    register_renderer(SCATTER_VIEW_KIND, Scatter2DHost)
    register_scene_contribution(
        SLICE_OVERLAY_KIND,
        PointCloudPlaneSliceRenderer,
    )
    register_scene_layer(
        VIEW_KIND,
        PointCloudVisual,
        from_view=PointCloudViewConfig.from_view,
        targets=(VIEW_KIND,),
        patch={VIEW_KIND: None},
        full_refresh=(VIEW_KIND,),
        field_id_props={"values_id": VIEW_KIND},
    )


__all__ = [
    "PointCloudViewConfig",
    "PointCloudVisual",
    "PointCloudPlaneSliceRenderer",
    "Scatter2DHost",
    "register",
]
