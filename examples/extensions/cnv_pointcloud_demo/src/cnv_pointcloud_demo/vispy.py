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
    RefreshTarget,
    register_3d_visual,
    register_operator_adapter,
    register_renderer,
)

from cnv_pointcloud_demo.authoring import (
    GEOMETRY_KIND,
    SCATTER_VIEW_KIND,
    VIEW_KIND,
)
from cnv_pointcloud_demo.slice_operator import (
    PointCloudSliceConfig,
    SLICE_FIELD_SCHEMA,
    SLICE_OPERATOR_KIND,
    SLICE_OVERLAY_TARGET,
    _contains_binding,
    field_from_point_cloud_slice,
    point_cloud_slice,
)


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
        self._scene = view.scene
        self._panel_id = panel_id
        self._markers = scene.visuals.Markers(parent=view.scene)
        self._markers.visible = False
        self._slice_planes: list[Any] = []
        self._positions = np.empty((0, 3), dtype=np.float32)
        self._entity_ids: tuple[str, ...] = ()
        self._colors = np.empty((0, 4), dtype=np.float32)
        self._point_size = 8.0

    def clear(self) -> None:
        self._markers.visible = False
        self._clear_slice_planes()

    def refresh_for_target(
        self,
        kind: str,
        view: PointCloudViewConfig,
        ctx,
    ) -> None:
        if kind == SLICE_OVERLAY_TARGET:
            self._refresh_slice_overlays(view, ctx)
            return
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

    def _clear_slice_planes(self) -> None:
        for plane in self._slice_planes:
            plane.parent = None
        self._slice_planes.clear()

    def _refresh_slice_overlays(
        self,
        view: PointCloudViewConfig,
        ctx,
    ) -> None:
        self._clear_slice_planes()
        if self._panel_id is None or ctx.active_layout is None:
            return
        panel = ctx.active_layout.panel(self._panel_id)
        if panel is None:
            return
        geometry_ref = cnv.app_ref(
            view.geometry_id,
            fragment_id=ctx.fragment_id,
        )
        geometry = ctx.app_spec.geometry(geometry_ref)
        if (
            not isinstance(geometry, cnv.ExtensionGeometrySpec)
            or geometry.kind != GEOMETRY_KIND
        ):
            return
        values_field = ctx.field(view.values_id)
        if values_field is None:
            return
        for operator_id in panel.operator_ids:
            operator_ref = cnv.app_ref(
                operator_id,
                fragment_id=ctx.fragment_id,
            )
            operator = ctx.app_spec.operator(operator_ref)
            if (
                not isinstance(operator, cnv.ExtensionOperatorSpec)
                or operator.kind != SLICE_OPERATOR_KIND
            ):
                continue
            config = PointCloudSliceConfig.from_extension(operator)
            if (
                cnv.app_ref(
                    config.geometry_id,
                    fragment_id=operator_ref.fragment_id,
                )
                != geometry_ref
            ):
                continue
            resolved = config.resolved(ctx.values, operator_ref.fragment_id)
            sliced = point_cloud_slice(geometry, values_field, resolved)
            self._add_slice_planes(sliced, resolved)

    def _add_slice_planes(self, sliced, config: PointCloudSliceConfig) -> None:
        rgba = np.asarray(Color(config.color).rgba, dtype=np.float32)
        fill = rgba.copy()
        fill[3] = float(np.clip(float(config.alpha), 0.0, 1.0))
        edge = rgba.copy()
        edge[3] = min(1.0, max(0.45, fill[3] * 4.0))
        other_indices = tuple(index for index in range(3) if index != sliced.axis_index)
        width = max(
            float(
                sliced.bounds_max[other_indices[0]]
                - sliced.bounds_min[other_indices[0]]
            ),
            1e-6,
        )
        height = max(
            float(
                sliced.bounds_max[other_indices[1]]
                - sliced.bounds_min[other_indices[1]]
            ),
            1e-6,
        )
        coordinates = {
            sliced.center - sliced.half_width,
            sliced.center + sliced.half_width,
        }
        for coordinate in sorted(coordinates):
            center = 0.5 * (sliced.bounds_min + sliced.bounds_max)
            center[sliced.axis_index] = coordinate
            plane = scene.visuals.Plane(
                width=width,
                height=height,
                direction=f"+{sliced.axis}",
                color=tuple(fill),
                edge_color=tuple(edge),
                parent=self._scene,
            )
            plane.transform = STTransform(translate=tuple(center))
            self._slice_planes.append(plane)

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


class Scatter2DHost(QtWidgets.QGroupBox):
    """Package-owned Qt/pyqtgraph host for projected point data."""

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
        view: cnv.ExtensionViewSpec,
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
        return PointCloudSliceConfig.from_extension(operator)

    def _slices_view(self, ctx) -> bool:
        geometry_id = getattr(ctx.view, "geometry_id", None)
        if geometry_id is None:
            return False
        config = self._config(ctx.op)
        return cnv.app_ref(
            config.geometry_id,
            fragment_id=ctx.op_ref.fragment_id,
        ) == cnv.app_ref(
            geometry_id,
            fragment_id=ctx.view_ref.fragment_id,
        )

    def on_value_change(self, ctx, value_key) -> set[RefreshTarget]:
        if not self._slices_view(ctx):
            return set()
        if _contains_binding(
            ctx.op.properties,
            value_key,
            ctx.op_ref.fragment_id,
        ):
            return {RefreshTarget(SLICE_OVERLAY_TARGET, ctx.view_id)}
        return set()

    def on_field_replace(self, ctx, field_ref) -> set[RefreshTarget]:
        del ctx, field_ref
        return set()

    def on_operator_patch(self, ctx, changed_props) -> set[RefreshTarget]:
        if self._slices_view(ctx):
            return {RefreshTarget(SLICE_OVERLAY_TARGET, ctx.view_id)}
        return set()

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
        if not isinstance(geometry, cnv.ExtensionGeometrySpec):
            raise TypeError("Point-cloud slice geometry must be an extension geometry")
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
    register_3d_visual(
        VIEW_KIND,
        PointCloudVisual,
        from_extension=PointCloudViewConfig.from_extension,
        targets=(VIEW_KIND, SLICE_OVERLAY_TARGET),
        patch={VIEW_KIND: None},
        full_refresh=(VIEW_KIND, SLICE_OVERLAY_TARGET),
        field_id_props={"values_id": VIEW_KIND},
    )


__all__ = [
    "PointCloudViewConfig",
    "PointCloudVisual",
    "Scatter2DHost",
    "register",
]
