"""Vispy rendering of the neutral ``kind="morphology"`` view.

This is the *vispy implementation* of the morphology widget: the abstract widget
(``inline/widgets/morphology.py``) authors a ``ViewSpec(kind="morphology")``
knowing nothing about vispy; this module renders that kind on the shared 3-D canvas.
It exposes an explicit callback that registers its visual and refresh schema, so
adding or removing morphology touches only its component and the composition root.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, ClassVar

import numpy as np
from vispy import scene

from compneurovis.core.runtime.performance import perf_log
from compneurovis.core.app_spec import app_ref
from compneurovis.core.views import ViewSpec, ValueOrBinding
from compneurovis.geometries.morphology import (
    MorphologyGeometry,
    morphology_geometry_from_spec,
)
from compneurovis.frontends.vispy.bindings import resolve_binding
from compneurovis.components.morphology.renderer import MorphologyRenderer
from compneurovis.components.morphology.authoring import (
    DEFAULT_MORPHOLOGY_CAMERA_ORBIT_SENSITIVITY,
    DEFAULT_MORPHOLOGY_CAMERA_PAN_SENSITIVITY,
    DEFAULT_MORPHOLOGY_CAMERA_ZOOM_SENSITIVITY,
)
from compneurovis.frontends.vispy.registries.scene_layers import (
    EntityPick,
    SceneLayerRefreshContext,
    register_scene_layer,
)
from compneurovis.frontends.vispy.registries.render_configs import ViewRenderConfig

MORPHOLOGY_3D_VISUAL_KEY = "morphology"


@dataclass(frozen=True, slots=True)
class MorphologyRenderConfig(ViewRenderConfig):
    """Vispy render-config for a morphology view. Not authored: the frontend rebuilds
    it from a ``ViewSpec(kind="morphology")`` at the refresh boundary."""

    kind: ClassVar[str] = MORPHOLOGY_3D_VISUAL_KEY
    geometry_id: str = "morphology"
    selection_id: str = ""
    entity_click_id: str = ""
    color_field_id: str | None = None
    entity_dim: str = "segment"
    sample_dim: str | None = "time"
    color_map: str = "scalar"
    color_limits: ValueOrBinding = None
    color_norm: str = "auto"
    background_color: ValueOrBinding = "white"
    # Initial camera pose — a 3-D view property, defaulted by this renderer alone.
    camera_distance: float | None = 200.0
    camera_elevation: float = 30.0
    camera_azimuth: float = 30.0
    camera_orbit_sensitivity: float = DEFAULT_MORPHOLOGY_CAMERA_ORBIT_SENSITIVITY
    camera_pan_sensitivity: float = DEFAULT_MORPHOLOGY_CAMERA_PAN_SENSITIVITY
    camera_zoom_sensitivity: float = DEFAULT_MORPHOLOGY_CAMERA_ZOOM_SENSITIVITY
    max_refresh_hz: float | None = None

    @classmethod
    def from_view(cls, view: "ViewSpec") -> "MorphologyRenderConfig":
        return cls(
            id=view.id,
            title=view.title,
            geometry_id=view.geometries.get("morphology", ""),
            selection_id=view.selections.get("entities", ""),
            entity_click_id=view.entity_clicks.get("entities", ""),
            color_field_id=view.inputs.get("color"),
            max_refresh_hz=view.max_refresh_hz,
            **dict(view.properties),
        )


class Morphology3DVisual:
    def __init__(self, view, *, panel_id: str | None = None):
        self._panel_id = panel_id
        self.renderer = MorphologyRenderer(view)
        self._active_geometry: MorphologyGeometry | None = None
        self._active_geometry_spec = None

    def clear(self) -> None:
        self.renderer.clear()
        self._active_geometry = None
        self._active_geometry_spec = None

    def refresh_for_target(
        self,
        kind: str,
        view: MorphologyRenderConfig,
        ctx: SceneLayerRefreshContext,
    ) -> None:
        geometry_spec = ctx.app_spec.geometry(
            app_ref(view.geometry_id, fragment_id=ctx.fragment_id)
        )
        geometry = (
            self._active_geometry
            if geometry_spec is self._active_geometry_spec
            else morphology_geometry_from_spec(geometry_spec)
        )
        if geometry is None:
            return
        self._active_geometry_spec = geometry_spec
        morphology_colors = None
        field_color_limits = None
        field_color_map = None
        if view.color_field_id:
            field = ctx.field(view.color_field_id)
            if field is not None:
                field_color_limits = field.attrs.get("color_limits")
                field_color_map = field.attrs.get("color_map")
                if view.sample_dim and view.sample_dim in field.dims:
                    morphology_colors = field.select({view.sample_dim: -1}).values
                else:
                    morphology_colors = field.values
        color_limits = resolve_binding(view.color_limits, ctx.values, ctx.fragment_id)
        if color_limits is None:
            color_limits = field_color_limits
        resolved_values = {
            f"{view.id}:background_color": resolve_binding(view.background_color, ctx.values, ctx.fragment_id),
            f"{view.id}:color_limits":     color_limits,
            f"{view.id}:color_norm":       view.color_norm,
            f"{view.id}:color_map":        field_color_map or view.color_map,
        }
        self.refresh(
            morphology_geometry=geometry,
            morphology_view=view,
            morphology_colors=morphology_colors,
            resolved_values=resolved_values,
        )

    def refresh(
        self,
        *,
        morphology_geometry: MorphologyGeometry | None,
        morphology_view: MorphologyRenderConfig | None,
        morphology_colors: np.ndarray | None,
        resolved_values: dict[str, Any],
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
                resolved_values.get(f"{morphology_view.id}:color_map", morphology_view.color_map),
                color_limits=resolved_values.get(f"{morphology_view.id}:color_limits", morphology_view.color_limits),
                color_norm=resolved_values.get(f"{morphology_view.id}:color_norm", morphology_view.color_norm),
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

    def pick_entity(
        self, xf: int, yf: int, canvas: scene.SceneCanvas
    ) -> EntityPick | None:
        if self._active_geometry is None:
            return None
        entity_id = self.renderer.pick(xf, yf, canvas)
        return (
            None
            if entity_id is None
            else EntityPick(interaction_role="entities", entity_id=entity_id)
        )

    def wants_entity_click(self, view) -> bool:
        # Picking is independent from selection consumption/presentation.
        return bool(getattr(view, "entity_click_id", ""))

    def refresh_overlays(self, host, view, ctx: SceneLayerRefreshContext) -> None:
        # Optional visual capability: drive the panel's scalar colorbar from the
        # morphology's color field. A visual without this hook gets no colorbar.
        if not view.color_field_id:
            host.clear_colorbar()
            return
        field = ctx.field(view.color_field_id)
        if field is None:
            host.clear_colorbar()
            return
        if view.sample_dim and view.sample_dim in field.dims:
            values = field.select({view.sample_dim: -1}).values
        else:
            values = field.values
        values = np.asarray(values, dtype=np.float32)
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            host.clear_colorbar()
            return
        limits = resolve_binding(view.color_limits, ctx.values, ctx.fragment_id)
        if limits is None:
            limits = field.attrs.get("color_limits")
        if limits is None:
            vmin = float(np.min(finite))
            vmax = float(np.max(finite))
        else:
            vmin = float(limits[0])
            vmax = float(limits[1])
        variable = str(field.attrs.get("variable", "")).strip()
        unit_value = field.attrs.get("unit", field.unit)
        unit = "" if unit_value is None else str(unit_value).strip()
        label = variable or field.id
        if unit:
            label = f"{label} ({unit})"
        color_map = field.attrs.get("color_map") or view.color_map
        host.set_colorbar(color_map=str(color_map), vmin=vmin, vmax=vmax, label=label)


def register_morphology_vispy() -> None:
    """Register the first-party Morphology Scene3D implementation."""
    register_scene_layer(
        MORPHOLOGY_3D_VISUAL_KEY,
        Morphology3DVisual,
        from_view=MorphologyRenderConfig.from_view,
        targets=(MORPHOLOGY_3D_VISUAL_KEY,),
        patch={MORPHOLOGY_3D_VISUAL_KEY: None},
        value_binding={
            MORPHOLOGY_3D_VISUAL_KEY: frozenset(
                {"background_color", "color_limits"}
            )
        },
        full_refresh=(MORPHOLOGY_3D_VISUAL_KEY,),
        field_id_props={"color_field_id": MORPHOLOGY_3D_VISUAL_KEY},
    )
