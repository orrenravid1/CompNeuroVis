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
from dataclasses import dataclass
from typing import Any, ClassVar

import numpy as np
from vispy import scene

from compneurovis.core._perf import perf_log
from compneurovis.core.app_spec import app_ref
from compneurovis.core.field import Field
from compneurovis.core.operators import ExtensionOperatorSpec
from compneurovis.core.views import ExtensionViewSpec, ValueOrBinding, ViewSpec
from compneurovis.frontends.vispy.renderers.surface import SurfaceRenderer
from compneurovis.frontends.vispy.view_inputs.bindings import _ref, resolve_binding
from compneurovis.frontends.vispy.view_inputs.grid_slice import (
    GRID_SLICE_OPERATOR_KIND,
    GridSliceOperatorConfig,
    OPERATOR_OVERLAY,
    grid_slice_config,
    overlay_from_grid_slice_operator,
)
from compneurovis.frontends.vispy.view_inputs.surface import (
    SurfaceSceneData,
    surface_scene_from_field,
)
from compneurovis.frontends.vispy.view3d.visuals import (
    SceneLayerRefreshContext,
    register_scene_layer,
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


@dataclass(frozen=True, slots=True)
class SurfaceViewSpec(ViewSpec):
    """Vispy render-config for a surface view. Not authored: the frontend rebuilds
    it from an ``ExtensionViewSpec(kind="surface")`` at the refresh boundary."""

    kind: ClassVar[str] = SURFACE_3D_VISUAL_KEY
    field_id: str = ""
    color_map: ValueOrBinding = "bwr"
    color_limits: ValueOrBinding = None
    color_by: ValueOrBinding = "height"
    surface_color: ValueOrBinding = (0.5, 0.6, 0.8, 1.0)
    surface_shading: ValueOrBinding = "unlit"
    surface_alpha: ValueOrBinding = 1.0
    background_color: ValueOrBinding = "white"
    render_axes: ValueOrBinding = False
    axes_in_middle: ValueOrBinding = True
    tick_count: ValueOrBinding = 5
    tick_length_scale: ValueOrBinding = 1.0
    tick_label_size: ValueOrBinding = 48.0
    axis_label_size: ValueOrBinding = 64.0
    axis_color: ValueOrBinding = "black"
    text_color: ValueOrBinding = "black"
    axis_alpha: ValueOrBinding = 1.0
    axis_labels: tuple[str, str, str] | None = None
    # Initial camera pose — a 3-D view property, defaulted by this renderer alone.
    camera_distance: float | None = 30.0
    camera_elevation: float = 30.0
    camera_azimuth: float = 30.0
    max_refresh_hz: float | None = None

    def __post_init__(self) -> None:
        if self.axis_labels is not None:
            object.__setattr__(self, "axis_labels", tuple(self.axis_labels))

    @classmethod
    def from_extension(cls, view: "ExtensionViewSpec") -> "SurfaceViewSpec":
        return cls(
            id=view.id,
            title=view.title,
            field_id=view.inputs.get("field", ""),
            max_refresh_hz=view.max_refresh_hz,
            **dict(view.properties),
        )


def _resolve_surface_values(view: SurfaceViewSpec, values: dict[str, Any], fragment_id: str) -> dict[str, Any]:
    keys = (
        "color_map", "color_limits", "color_by", "surface_color", "surface_shading",
        "surface_alpha", "background_color", "render_axes", "axes_in_middle",
        "tick_count", "tick_length_scale", "tick_label_size", "axis_label_size",
        "axis_color", "text_color", "axis_alpha",
    )
    return {f"{view.id}:{k}": resolve_binding(getattr(view, k), values, fragment_id) for k in keys}


def _get_panel_slice_operators(
    ctx: SceneLayerRefreshContext,
    view: SurfaceViewSpec,
) -> list[ExtensionOperatorSpec]:
    panel = ctx.active_layout.panel_for_view(ctx.view_id, kind="scene_3d")
    if panel is None:
        return []
    ops = []
    for op_id in panel.operator_ids:
        op_ref = app_ref(op_id, fragment_id=ctx.fragment_id)
        op = ctx.app_spec.operator(op_ref)
        if (
            not isinstance(op, ExtensionOperatorSpec)
            or op.kind != GRID_SLICE_OPERATOR_KIND
        ):
            continue
        config = grid_slice_config(op)
        if app_ref(config.field_id, fragment_id=op_ref.fragment_id) != app_ref(
            view.field_id, fragment_id=ctx.fragment_id
        ):
            continue
        ops.append(op)
    return ops


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
        ctx: SceneLayerRefreshContext,
    ) -> None:
        resolved_values = _resolve_surface_values(view, ctx.values, ctx.fragment_id)
        if kind == SURFACE_VISUAL:
            surface_field = ctx.field(view.field_id)
            if surface_field is None:
                return
            self.refresh_visual(
                surface_view=view,
                surface_field=surface_field,
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
                operators=[
                    grid_slice_config(op).resolved(ctx.values, ctx.fragment_id)
                    for op in operators
                ],
            )

    def refresh_visual(
        self,
        *,
        surface_view: SurfaceViewSpec | None,
        surface_field: Field | None,
        resolved_values: dict[str, Any],
    ) -> None:
        started = time.monotonic()
        if surface_view is None or surface_field is None:
            return

        coords_changed = self._refresh_scene_data(surface_field)
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
        operators: list[GridSliceOperatorConfig],
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

    def _refresh_scene_data(self, surface_field: Field) -> bool:
        coord_key = self._surface_coord_key(surface_field)
        coords_changed = coord_key != self._coord_key
        if coords_changed:
            self.scene_data = surface_scene_from_field(surface_field)
            self._coord_key = coord_key
            return True
        self.scene_data = self._scene_data_with_updated_values(surface_field)
        return False

    def _surface_coord_key(self, surface_field: Field) -> tuple:
        return (surface_field.id,) + tuple(
            (id(coord), coord.shape) for coord in surface_field.coords.values()
        )

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

register_scene_layer(
    SURFACE_3D_VISUAL_KEY,
    Surface3DVisual,
    from_extension=SurfaceViewSpec.from_extension,
    targets=SURFACE_TARGETS,
    patch={
        SURFACE_VISUAL:        frozenset({"field_id", "max_refresh_hz"}),
        SURFACE_STYLE:         frozenset({"color_map", "color_limits", "color_by",
                                          "surface_color", "surface_shading", "surface_alpha",
                                          "background_color"}),
        SURFACE_AXES_GEOMETRY: frozenset({"field_id", "render_axes",
                                          "axes_in_middle", "tick_count", "tick_length_scale",
                                          "axis_labels"}),
        SURFACE_AXES_STYLE:    frozenset({"tick_label_size", "axis_label_size",
                                          "axis_color", "text_color", "axis_alpha"}),
        OPERATOR_OVERLAY:      frozenset({"field_id"}),
    },
    value_binding={
        SURFACE_VISUAL:        frozenset({"field_id"}),
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
