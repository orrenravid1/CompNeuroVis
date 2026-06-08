from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping

import numpy as np
from vispy import scene

from compneurovis.core._perf import perf_log
from compneurovis.core.field import Field
from compneurovis.core.geometry import GridGeometrySpec, MorphologyGeometrySpec
from compneurovis.core.operators import GridSliceOperatorSpec
from compneurovis.core.app_spec import PANEL_KIND_VIEW_3D
from compneurovis.core.views import MorphologyViewSpec, SurfaceViewSpec
from compneurovis.frontends.vispy.refresh_planning import resolve_value
from compneurovis.frontends.vispy.view_inputs.grid_slice import overlay_from_grid_slice_operator
from compneurovis.frontends.vispy.view_inputs.surface import SurfaceSceneData, surface_scene_from_field
from compneurovis.frontends.vispy.renderers.morphology import MorphologyRenderer
from compneurovis.frontends.vispy.renderers.surface import SurfaceRenderer
from compneurovis.frontends.vispy.view3d.viewport import Viewport3DVisual

if TYPE_CHECKING:
    from compneurovis.core.app_spec import AppSpec


@dataclass
class View3DRefreshContext:
    app_spec: "AppSpec"
    state: dict[str, Any]
    view_id: str
    fields: "Mapping[str, Field]" = field(default_factory=dict)
    active_layout: "Any" = None  # live LayoutSpec (AppProjection-resolved), not the blueprint default

    def field(self, field_id: str | None):
        """Live materialized field value from AppProjection (never the blueprint)."""
        if not field_id:
            return None
        return self.fields.get(field_id)


MORPHOLOGY_3D_VISUAL_KEY = "morphology"
SURFACE_3D_VISUAL_KEY = "surface"


def builtin_3d_visuals(view, *, panel_id: str | None = None) -> dict[str, Viewport3DVisual]:
    return {
        MORPHOLOGY_3D_VISUAL_KEY: Morphology3DVisual(view, panel_id=panel_id),
        SURFACE_3D_VISUAL_KEY: Surface3DVisual(view, panel_id=panel_id),
    }


def _resolve_surface_state(view: SurfaceViewSpec, state: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "color_map", "color_limits", "color_by", "surface_color", "surface_shading",
        "surface_alpha", "background_color", "render_axes", "axes_in_middle",
        "tick_count", "tick_length_scale", "tick_label_size", "axis_label_size",
        "axis_color", "text_color", "axis_alpha",
    )
    return {f"{view.id}:{k}": resolve_value(getattr(view, k), state) for k in keys}


def _get_panel_slice_operators(ctx: View3DRefreshContext, view: SurfaceViewSpec) -> list[GridSliceOperatorSpec]:
    panel = ctx.active_layout.panel_for_view(ctx.view_id, kind=PANEL_KIND_VIEW_3D)
    if panel is None:
        return []
    ops = []
    for op_id in panel.operator_ids:
        op = ctx.app_spec.view_catalog.operators.get(op_id)
        if not isinstance(op, GridSliceOperatorSpec):
            continue
        if op.field_id != view.field_id or op.geometry_id not in {None, view.geometry_id}:
            continue
        ops.append(op)
    return ops


def _resolve_operator_state(op: GridSliceOperatorSpec, state: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        f"{op.id}:color":      resolve_value(op.color, state),
        f"{op.id}:alpha":      resolve_value(op.alpha, state),
        f"{op.id}:fill_alpha": resolve_value(op.fill_alpha, state),
        f"{op.id}:width":      resolve_value(op.width, state),
    }
    if op.axis_state_key:
        result[op.axis_state_key] = state.get(op.axis_state_key)
    if op.position_state_key:
        result[op.position_state_key] = state.get(op.position_state_key)
    return result


class Morphology3DVisual:
    def __init__(self, view, *, panel_id: str | None = None):
        self._panel_id = panel_id
        self.renderer = MorphologyRenderer(view)
        self._active_geometry: MorphologyGeometrySpec | None = None

    def clear(self) -> None:
        self.renderer.clear()
        self._active_geometry = None

    def refresh_for_target(
        self,
        kind: str,
        view: MorphologyViewSpec,
        ctx: View3DRefreshContext,
    ) -> None:
        geometry = ctx.app_spec.data.geometries.get(view.geometry_id)
        if not isinstance(geometry, MorphologyGeometrySpec):
            return
        morphology_colors = None
        field_color_limits = None
        if view.color_field_id:
            field = ctx.field(view.color_field_id)
            if field is not None:
                field_color_limits = field.attrs.get("color_limits")
                if view.sample_dim and view.sample_dim in field.dims:
                    morphology_colors = field.select({view.sample_dim: -1}).values
                else:
                    morphology_colors = field.values
        color_limits = resolve_value(view.color_limits, ctx.state)
        if color_limits is None:
            color_limits = field_color_limits
        resolved_state = {
            f"{view.id}:background_color": resolve_value(view.background_color, ctx.state),
            f"{view.id}:color_limits":     color_limits,
            f"{view.id}:color_norm":       view.color_norm,
        }
        self.refresh(
            morphology_geometry=geometry,
            morphology_view=view,
            morphology_colors=morphology_colors,
            resolved_state=resolved_state,
        )

    def refresh(
        self,
        *,
        morphology_geometry: MorphologyGeometrySpec | None,
        morphology_view: MorphologyViewSpec | None,
        morphology_colors: np.ndarray | None,
        resolved_state: dict[str, Any],
    ) -> None:
        started = time.monotonic()
        if morphology_view is None or morphology_geometry is None:
            return

        self._active_geometry = morphology_geometry
        geometry_changed = self.renderer.geometry is not morphology_geometry
        set_geometry_ms = 0.0
        update_colors_ms = 0.0
        if geometry_changed:
            geometry_started = time.monotonic()
            self.renderer.set_geometry(morphology_geometry)
            set_geometry_ms = round((time.monotonic() - geometry_started) * 1000.0, 3)
        if morphology_colors is not None:
            color_started = time.monotonic()
            self.renderer.update_colors(
                morphology_colors,
                morphology_view.color_map,
                color_limits=resolved_state.get(f"{morphology_view.id}:color_limits", morphology_view.color_limits),
                color_norm=resolved_state.get(f"{morphology_view.id}:color_norm", morphology_view.color_norm),
            )
            update_colors_ms = round((time.monotonic() - color_started) * 1000.0, 3)
        perf_log(
            "view_3d",
            "refresh_morphology",
            panel_id=self._panel_id,
            view_id=morphology_view.id,
            geometry_changed=geometry_changed,
            segment_count=len(morphology_geometry.entity_ids),
            has_colors=morphology_colors is not None,
            set_geometry_ms=set_geometry_ms,
            update_colors_ms=update_colors_ms,
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )

    def pick_entity(self, xf: int, yf: int, canvas: scene.SceneCanvas) -> str | None:
        if self._active_geometry is None:
            return None
        return self.renderer.pick(xf, yf, canvas)


class Surface3DVisual:
    def __init__(self, view, *, panel_id: str | None = None):
        self._panel_id = panel_id
        self.renderer = SurfaceRenderer(view)
        self.scene_data: SurfaceSceneData | None = None
        self._coord_key: tuple | None = None

    def clear(self) -> None:
        self.renderer.clear()
        self.scene_data = None
        self._coord_key = None

    def refresh_for_target(
        self,
        kind: str,
        view: SurfaceViewSpec,
        ctx: View3DRefreshContext,
    ) -> None:
        resolved_state = _resolve_surface_state(view, ctx.state)
        if kind == "surface_visual":
            surface_field = ctx.field(view.field_id)
            if surface_field is None:
                return
            grid_geometry = ctx.app_spec.data.geometries.get(view.geometry_id) if view.geometry_id else None
            self.refresh_visual(
                surface_view=view,
                surface_field=surface_field,
                grid_geometry=grid_geometry,
                resolved_state=resolved_state,
            )
        elif kind == "surface_style":
            self.refresh_style(surface_view=view, resolved_state=resolved_state)
        elif kind == "surface_axes_geometry":
            self.refresh_axes_geometry(surface_view=view, resolved_state=resolved_state)
        elif kind == "surface_axes_style":
            self.refresh_axes_style(surface_view=view, resolved_state=resolved_state)
        elif kind == "operator_overlay":
            operators = _get_panel_slice_operators(ctx, view)
            self.refresh_operator_overlays(
                surface_view=view,
                operators=operators,
                resolved_operator_states={op.id: _resolve_operator_state(op, ctx.state) for op in operators},
            )

    def refresh_visual(
        self,
        *,
        surface_view: SurfaceViewSpec | None,
        surface_field: Field | None,
        grid_geometry: GridGeometrySpec | None,
        resolved_state: dict[str, Any],
    ) -> None:
        started = time.monotonic()
        if surface_view is None or surface_field is None:
            return

        coords_changed = self._refresh_scene_data(surface_field, grid_geometry)
        assert self.scene_data is not None
        self.renderer.update_surface(
            self.scene_data.x_grid,
            self.scene_data.y_grid,
            self.scene_data.z,
            color_map=resolved_state[f"{surface_view.id}:color_map"],
            color_limits=resolved_state[f"{surface_view.id}:color_limits"],
            colors=None,
            color_by=resolved_state[f"{surface_view.id}:color_by"],
            surface_color=resolved_state[f"{surface_view.id}:surface_color"],
            surface_shading=resolved_state[f"{surface_view.id}:surface_shading"],
            surface_alpha=resolved_state[f"{surface_view.id}:surface_alpha"],
            coords_changed=coords_changed,
        )
        perf_log(
            "view_3d",
            "refresh_surface_visual",
            panel_id=self._panel_id,
            view_id=surface_view.id,
            coords_changed=coords_changed,
            field_shape=getattr(surface_field.values, "shape", None),
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )

    def refresh_style(
        self,
        *,
        surface_view: SurfaceViewSpec | None,
        resolved_state: dict[str, Any],
    ) -> None:
        started = time.monotonic()
        if surface_view is None or self.scene_data is None:
            return

        self.renderer.update_surface_style(
            self.scene_data.z,
            color_map=resolved_state[f"{surface_view.id}:color_map"],
            color_limits=resolved_state[f"{surface_view.id}:color_limits"],
            colors=None,
            color_by=resolved_state[f"{surface_view.id}:color_by"],
            surface_color=resolved_state[f"{surface_view.id}:surface_color"],
            surface_shading=resolved_state[f"{surface_view.id}:surface_shading"],
            surface_alpha=resolved_state[f"{surface_view.id}:surface_alpha"],
        )
        perf_log(
            "view_3d",
            "refresh_surface_style",
            panel_id=self._panel_id,
            view_id=surface_view.id,
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )

    def refresh_axes_geometry(
        self,
        *,
        surface_view: SurfaceViewSpec | None,
        resolved_state: dict[str, Any],
    ) -> None:
        started = time.monotonic()
        if surface_view is None or self.scene_data is None:
            self.renderer.axes.clear()
            return

        axis_labels = surface_view.axis_labels or (
            self.scene_data.x_dim,
            self.scene_data.y_dim,
            self.scene_data.field_id,
        )
        self.renderer.axes.set_axes_geometry(
            render_axes=resolved_state[f"{surface_view.id}:render_axes"],
            axes_in_middle=resolved_state[f"{surface_view.id}:axes_in_middle"],
            tick_count=resolved_state[f"{surface_view.id}:tick_count"],
            tick_length_scale=resolved_state[f"{surface_view.id}:tick_length_scale"],
            axis_labels=axis_labels,
            x=self.scene_data.x_grid,
            y=self.scene_data.y_grid,
            z=self.scene_data.z,
        )
        self._apply_axes_style(surface_view, resolved_state)
        perf_log(
            "view_3d",
            "refresh_surface_axes_geometry",
            panel_id=self._panel_id,
            view_id=surface_view.id,
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )

    def refresh_axes_style(
        self,
        *,
        surface_view: SurfaceViewSpec | None,
        resolved_state: dict[str, Any],
    ) -> None:
        started = time.monotonic()
        if surface_view is None or self.scene_data is None:
            self.renderer.axes.clear()
            return

        self._apply_axes_style(surface_view, resolved_state)
        perf_log(
            "view_3d",
            "refresh_surface_axes_style",
            panel_id=self._panel_id,
            view_id=surface_view.id,
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )

    def _apply_axes_style(self, surface_view: SurfaceViewSpec, resolved_state: dict[str, Any]) -> None:
        self.renderer.axes.set_axes_style(
            render_axes=resolved_state[f"{surface_view.id}:render_axes"],
            tick_label_size=resolved_state[f"{surface_view.id}:tick_label_size"],
            axis_label_size=resolved_state[f"{surface_view.id}:axis_label_size"],
            axis_color=resolved_state[f"{surface_view.id}:axis_color"],
            text_color=resolved_state[f"{surface_view.id}:text_color"],
            axis_alpha=resolved_state[f"{surface_view.id}:axis_alpha"],
        )

    def refresh_operator_overlays(
        self,
        *,
        surface_view: SurfaceViewSpec | None,
        operators: list[GridSliceOperatorSpec],
        resolved_operator_states: dict[str, dict[str, Any]],
    ) -> None:
        started = time.monotonic()
        if surface_view is None or self.scene_data is None or not operators:
            self.renderer.clear_operator_overlays()
            return

        overlays = []
        for operator in operators:
            overlay = overlay_from_grid_slice_operator(
                self.scene_data,
                operator,
                resolved_operator_states.get(operator.id, {}),
            )
            if overlay is not None:
                overlays.append(overlay)
        if not overlays:
            self.renderer.clear_operator_overlays()
            return
        self.renderer.set_slice_operator_overlays(
            overlays,
            x=self.scene_data.x_grid,
            y=self.scene_data.y_grid,
            z=self.scene_data.z,
        )
        perf_log(
            "view_3d",
            "refresh_operator_overlays",
            panel_id=self._panel_id,
            view_id=surface_view.id,
            overlay_count=len(overlays),
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )

    def pick_entity(self, xf: int, yf: int, canvas: scene.SceneCanvas) -> str | None:
        return None

    def _refresh_scene_data(self, surface_field: Field, grid_geometry: GridGeometrySpec | None) -> bool:
        coord_key = self._surface_coord_key(surface_field, grid_geometry)
        coords_changed = coord_key != self._coord_key
        if coords_changed:
            self.scene_data = surface_scene_from_field(surface_field, grid_geometry)
            self._coord_key = coord_key
            return True
        self.scene_data = self._scene_data_with_updated_values(surface_field)
        return False

    def _surface_coord_key(self, surface_field: Field, grid_geometry: GridGeometrySpec | None) -> tuple:
        if grid_geometry is not None:
            return (grid_geometry.id,) + tuple(c.shape for c in grid_geometry.coords.values())
        return (surface_field.id,) + tuple(c.shape for c in surface_field.coords.values())

    def _scene_data_with_updated_values(self, surface_field: Field) -> SurfaceSceneData:
        assert self.scene_data is not None
        z = surface_field.values
        if surface_field.dims != (self.scene_data.y_dim, self.scene_data.x_dim):
            axis_map = {dim: idx for idx, dim in enumerate(surface_field.dims)}
            z = np.transpose(z, (axis_map[self.scene_data.y_dim], axis_map[self.scene_data.x_dim]))
        return SurfaceSceneData(
            field_id=self.scene_data.field_id,
            x_dim=self.scene_data.x_dim,
            y_dim=self.scene_data.y_dim,
            x_grid=self.scene_data.x_grid,
            y_grid=self.scene_data.y_grid,
            z=np.asarray(z, dtype=np.float32),
            coords=self.scene_data.coords,
        )
