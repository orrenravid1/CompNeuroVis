"""Vispy rendering of the neutral ``kind="surface"`` view.

The *vispy implementation* of the surface widget: the abstract widget
(``inline/widgets/surface.py``) authors an ``ExtensionViewSpec(kind="surface")``
knowing nothing about vispy; this module renders that kind on the shared 3-D canvas
and self-registers its visual + its (vispy-specific) refresh schema against the kind.

The refresh sub-targets (``surface_visual``/``surface_style``/``surface_axes_*``) are
vispy render-stage names, owned here -- one source for the visual's dispatch, the
planner schema, and the frontend registry. ``operator_overlay`` is owned by the grid
slice (which contributes the overlay); the surface only *renders* it, so its name is
imported from the slice module.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np
from vispy import scene

from compneurovis.core._perf import perf_log
from compneurovis.core.app_spec import PANEL_KIND_VIEW_3D, app_ref
from compneurovis.core.field import Field
from compneurovis.core.geometry import GridGeometrySpec
from compneurovis.core.operators import GridSliceOperatorSpec
from compneurovis.core.views import SurfaceViewSpec
from compneurovis.frontends.vispy.refresh_planning import (
    _ref,
    register_view_refresh_schema,
    resolve_value,
)
from compneurovis.frontends.vispy.renderers.surface import SurfaceRenderer
from compneurovis.frontends.vispy.view_inputs.grid_slice import (
    OPERATOR_OVERLAY,
    overlay_from_grid_slice_operator,
)
from compneurovis.frontends.vispy.view_inputs.surface import (
    SurfaceSceneData,
    surface_scene_from_field,
)
from compneurovis.frontends.vispy.view3d.visuals import (
    View3DRefreshContext,
    register_3d_visual,
)

SURFACE_3D_VISUAL_KEY = "surface"

# Surface refresh sub-targets (vispy render stages), named once here.
SURFACE_VISUAL = "surface_visual"
SURFACE_STYLE = "surface_style"
SURFACE_AXES_GEOMETRY = "surface_axes_geometry"
SURFACE_AXES_STYLE = "surface_axes_style"
# The surface's ordered refresh targets. ``OPERATOR_OVERLAY`` (grid-slice-owned) is
# rendered by this visual too, so it is one of the surface's targets.
SURFACE_TARGETS = (
    SURFACE_VISUAL,
    SURFACE_STYLE,
    SURFACE_AXES_GEOMETRY,
    SURFACE_AXES_STYLE,
    OPERATOR_OVERLAY,
)


def _resolve_surface_values(view: SurfaceViewSpec, values: dict[str, Any], fragment_id: str) -> dict[str, Any]:
    keys = (
        "color_map", "color_limits", "color_by", "surface_color", "surface_shading",
        "surface_alpha", "background_color", "render_axes", "axes_in_middle",
        "tick_count", "tick_length_scale", "tick_label_size", "axis_label_size",
        "axis_color", "text_color", "axis_alpha",
    )
    return {f"{view.id}:{k}": resolve_value(getattr(view, k), values, fragment_id) for k in keys}


def _get_panel_slice_operators(ctx: View3DRefreshContext, view: SurfaceViewSpec) -> list[GridSliceOperatorSpec]:
    panel = ctx.active_layout.panel_for_view(ctx.view_id, kind=PANEL_KIND_VIEW_3D)
    if panel is None:
        return []
    ops = []
    for op_id in panel.operator_ids:
        op_ref = app_ref(op_id, fragment_id=ctx.fragment_id)
        op = ctx.app_spec.operator(op_ref)
        if not isinstance(op, GridSliceOperatorSpec):
            continue
        if (
            app_ref(op.field_id, fragment_id=op_ref.fragment_id) != app_ref(view.field_id, fragment_id=ctx.fragment_id)
            or (None if op.geometry_id is None else app_ref(op.geometry_id, fragment_id=op_ref.fragment_id))
            not in {None, None if view.geometry_id is None else app_ref(view.geometry_id, fragment_id=ctx.fragment_id)}
        ):
            continue
        ops.append(op)
    return ops


def _operator_control_value(key: str, values: dict[Any, Any], fragment_id: str | None) -> Any:
    """Read a raw control value key, which the frontend stores fragment-scoped."""
    if fragment_id is not None:
        scoped = app_ref(key, fragment_id=fragment_id)
        if scoped in values:
            return values.get(scoped)
    return values.get(key)


def _resolve_operator_values(op: GridSliceOperatorSpec, values: dict[str, Any], fragment_id: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        f"{op.id}:color":      resolve_value(op.color, values, fragment_id),
        f"{op.id}:alpha":      resolve_value(op.alpha, values, fragment_id),
        f"{op.id}:fill_alpha": resolve_value(op.fill_alpha, values, fragment_id),
        f"{op.id}:width":      resolve_value(op.width, values, fragment_id),
    }
    # Leave an unresolved key out entirely, so the reader's own default applies
    # rather than a None that would defeat it.
    for key in (op.axis_value_key, op.position_value_key):
        if not key:
            continue
        value = _operator_control_value(key, values, fragment_id)
        if value is not None:
            result[key] = value
    return result


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
        resolved_values = _resolve_surface_values(view, ctx.values, ctx.fragment_id)
        if kind == SURFACE_VISUAL:
            surface_field = ctx.field(view.field_id)
            if surface_field is None:
                return
            grid_geometry = ctx.app_spec.geometry(app_ref(view.geometry_id, fragment_id=ctx.fragment_id)) if view.geometry_id else None
            self.refresh_visual(
                surface_view=view,
                surface_field=surface_field,
                grid_geometry=grid_geometry,
                resolved_values=resolved_values,
            )
        elif kind == SURFACE_STYLE:
            self.refresh_style(surface_view=view, resolved_values=resolved_values)
        elif kind == SURFACE_AXES_GEOMETRY:
            self.refresh_axes_geometry(surface_view=view, resolved_values=resolved_values)
        elif kind == SURFACE_AXES_STYLE:
            self.refresh_axes_style(surface_view=view, resolved_values=resolved_values)
        elif kind == OPERATOR_OVERLAY:
            operators = _get_panel_slice_operators(ctx, view)
            self.refresh_operator_overlays(
                surface_view=view,
                operators=operators,
                resolved_operator_values={op.id: _resolve_operator_values(op, ctx.values, ctx.fragment_id) for op in operators},
            )

    def refresh_visual(
        self,
        *,
        surface_view: SurfaceViewSpec | None,
        surface_field: Field | None,
        grid_geometry: GridGeometrySpec | None,
        resolved_values: dict[str, Any],
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
            color_map=resolved_values[f"{surface_view.id}:color_map"],
            color_limits=resolved_values[f"{surface_view.id}:color_limits"],
            colors=None,
            color_by=resolved_values[f"{surface_view.id}:color_by"],
            surface_color=resolved_values[f"{surface_view.id}:surface_color"],
            surface_shading=resolved_values[f"{surface_view.id}:surface_shading"],
            surface_alpha=resolved_values[f"{surface_view.id}:surface_alpha"],
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
        resolved_values: dict[str, Any],
    ) -> None:
        started = time.monotonic()
        if surface_view is None or self.scene_data is None:
            return

        self.renderer.update_surface_style(
            self.scene_data.z,
            color_map=resolved_values[f"{surface_view.id}:color_map"],
            color_limits=resolved_values[f"{surface_view.id}:color_limits"],
            colors=None,
            color_by=resolved_values[f"{surface_view.id}:color_by"],
            surface_color=resolved_values[f"{surface_view.id}:surface_color"],
            surface_shading=resolved_values[f"{surface_view.id}:surface_shading"],
            surface_alpha=resolved_values[f"{surface_view.id}:surface_alpha"],
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
        resolved_values: dict[str, Any],
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
            render_axes=resolved_values[f"{surface_view.id}:render_axes"],
            axes_in_middle=resolved_values[f"{surface_view.id}:axes_in_middle"],
            tick_count=resolved_values[f"{surface_view.id}:tick_count"],
            tick_length_scale=resolved_values[f"{surface_view.id}:tick_length_scale"],
            axis_labels=axis_labels,
            x=self.scene_data.x_grid,
            y=self.scene_data.y_grid,
            z=self.scene_data.z,
        )
        self._apply_axes_style(surface_view, resolved_values)
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
        resolved_values: dict[str, Any],
    ) -> None:
        started = time.monotonic()
        if surface_view is None or self.scene_data is None:
            self.renderer.axes.clear()
            return

        self._apply_axes_style(surface_view, resolved_values)
        perf_log(
            "view_3d",
            "refresh_surface_axes_style",
            panel_id=self._panel_id,
            view_id=surface_view.id,
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )

    def _apply_axes_style(self, surface_view: SurfaceViewSpec, resolved_values: dict[str, Any]) -> None:
        self.renderer.axes.set_axes_style(
            render_axes=resolved_values[f"{surface_view.id}:render_axes"],
            tick_label_size=resolved_values[f"{surface_view.id}:tick_label_size"],
            axis_label_size=resolved_values[f"{surface_view.id}:axis_label_size"],
            axis_color=resolved_values[f"{surface_view.id}:axis_color"],
            text_color=resolved_values[f"{surface_view.id}:text_color"],
            axis_alpha=resolved_values[f"{surface_view.id}:axis_alpha"],
        )

    def refresh_operator_overlays(
        self,
        *,
        surface_view: SurfaceViewSpec | None,
        operators: list[GridSliceOperatorSpec],
        resolved_operator_values: dict[str, dict[str, Any]],
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
                resolved_operator_values.get(operator.id, {}),
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


def _surface_field_replace(target, view, view_id, field_ref, fragment_id, coords_changed):
    """Surface's field-replace routing -- conditional, so a hook not a static table.

    A replaced surface field always repaints the visual; it only rebuilds the axes
    geometry when the coordinates changed (or auto color-limits must be recomputed).
    """
    targets: set = set()
    if _ref(view.field_id, fragment_id) == field_ref:
        targets.add(target(SURFACE_VISUAL, view_id))
        if coords_changed or view.color_limits is None:
            targets.add(target(SURFACE_AXES_GEOMETRY, view_id))
    return targets


# --- self-registration: bind the neutral kind to this vispy impl + its schema ---

register_3d_visual(SURFACE_3D_VISUAL_KEY, Surface3DVisual, targets=SURFACE_TARGETS)
register_view_refresh_schema(
    SURFACE_3D_VISUAL_KEY,
    patch={
        SURFACE_VISUAL:        frozenset({"field_id", "geometry_id", "max_refresh_hz"}),
        SURFACE_STYLE:         frozenset({"color_map", "color_limits", "color_by",
                                          "surface_color", "surface_shading", "surface_alpha",
                                          "background_color"}),
        SURFACE_AXES_GEOMETRY: frozenset({"field_id", "geometry_id", "render_axes",
                                          "axes_in_middle", "tick_count", "tick_length_scale",
                                          "axis_labels"}),
        SURFACE_AXES_STYLE:    frozenset({"tick_label_size", "axis_label_size",
                                          "axis_color", "text_color", "axis_alpha"}),
        OPERATOR_OVERLAY:      frozenset({"field_id", "geometry_id"}),
    },
    value_binding={
        SURFACE_VISUAL:        frozenset({"field_id", "geometry_id"}),
        SURFACE_STYLE:         frozenset({"color_map", "color_limits", "color_by",
                                          "surface_color", "surface_shading", "surface_alpha",
                                          "background_color"}),
        SURFACE_AXES_GEOMETRY: frozenset({"render_axes", "axes_in_middle",
                                          "tick_count", "tick_length_scale"}),
        SURFACE_AXES_STYLE:    frozenset({"tick_label_size", "axis_label_size",
                                          "axis_color", "text_color", "axis_alpha"}),
    },
    full_refresh=(SURFACE_VISUAL, SURFACE_AXES_GEOMETRY, OPERATOR_OVERLAY),
    field_replace_hook=_surface_field_replace,
)
