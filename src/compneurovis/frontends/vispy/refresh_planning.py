from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from compneurovis.core import (
    BarPlotViewSpec,
    GridSliceOperatorSpec,
    LinePlotViewSpec,
    MorphologyViewSpec,
    AppSpec,
    StateBindingSpec,
    StateGraphViewSpec,
    SurfaceViewSpec,
)
from compneurovis.core.app_spec import (
    PANEL_KIND_LINE_PLOT,
    PANEL_KIND_STATE_GRAPH,
    PANEL_KIND_VIEW_3D,
)

# --- Schemas -----------------------------------------------------------------
#
# These replace hardcoded per-type logic in RefreshPlanner.  Adding a new view
# type means adding an entry here; no planner method needs to change.

# Maps view type → {target_kind → props that trigger it on a view patch}.
# None means "any changed prop triggers this target".
_VIEW_PATCH_SCHEMA: dict[type, dict[str, frozenset[str] | None]] = {
    MorphologyViewSpec: {
        "morphology": None,
    },
    SurfaceViewSpec: {
        "surface_visual":        frozenset({"field_id", "geometry_id", "max_refresh_hz"}),
        "surface_style":         frozenset({"color_map", "color_limits", "color_by",
                                            "surface_color", "surface_shading", "surface_alpha",
                                            "background_color"}),
        "surface_axes_geometry": frozenset({"field_id", "geometry_id", "render_axes",
                                            "axes_in_middle", "tick_count", "tick_length_scale",
                                            "axis_labels"}),
        "surface_axes_style":    frozenset({"tick_label_size", "axis_label_size",
                                            "axis_color", "text_color", "axis_alpha"}),
        "operator_overlay":      frozenset({"field_id", "geometry_id"}),
    },
    LinePlotViewSpec: {
        "line_plot": frozenset({
            "field_id", "operator_id", "x_dim", "series_dim", "selectors",
            "x_label", "y_label", "x_unit", "y_unit",
            "pen", "background_color", "title", "show_legend",
            "series_colors", "series_palette",
            "rolling_window", "trim_to_rolling_window", "max_refresh_hz",
            "y_min", "y_max", "x_major_tick_spacing", "x_minor_tick_spacing",
        }),
    },
    StateGraphViewSpec: {
        "state_graph": None,
    },
    # Bars reuse the line-plot panel/flush machinery, so they target "line_plot".
    BarPlotViewSpec: {
        "line_plot": None,
    },
}

# Maps view type -> {target_kind -> ValueOrBinding props} for binding-value checks.
# Only props that can actually be StateBindingSpec references need to appear here.
_VIEW_STATE_BINDING_SCHEMA: dict[type, dict[str, frozenset[str]]] = {
    MorphologyViewSpec: {
        "morphology": frozenset({"background_color", "color_limits"}),
    },
    SurfaceViewSpec: {
        "surface_visual":        frozenset({"field_id", "geometry_id"}),
        "surface_style":         frozenset({"color_map", "color_limits", "color_by",
                                            "surface_color", "surface_shading", "surface_alpha",
                                            "background_color"}),
        "surface_axes_geometry": frozenset({"render_axes", "axes_in_middle",
                                            "tick_count", "tick_length_scale"}),
        "surface_axes_style":    frozenset({"tick_label_size", "axis_label_size",
                                            "axis_color", "text_color", "axis_alpha"}),
    },
    LinePlotViewSpec: {
        "line_plot": frozenset({"pen", "background_color", "title"}),
    },
}

# Maps view type → target kinds included in a full app spec refresh.
_VIEW_FULL_REFRESH_KINDS: dict[type, tuple[str, ...]] = {
    MorphologyViewSpec:  ("morphology",),
    SurfaceViewSpec:     ("surface_visual", "surface_axes_geometry", "operator_overlay"),
    LinePlotViewSpec:    ("line_plot",),
    BarPlotViewSpec:     ("line_plot",),
    StateGraphViewSpec:  ("state_graph",),
}

# Maps view type → {field-id prop name → target kind} for field-replace routing.
# Surface omitted: its conditional axes-geometry logic is handled inline.
_VIEW_FIELD_ID_PROPS: dict[type, dict[str, str]] = {
    MorphologyViewSpec: {"color_field_id": "morphology"},
    LinePlotViewSpec:   {"field_id": "line_plot"},
    BarPlotViewSpec:    {"field_id": "line_plot"},
    StateGraphViewSpec: {"node_field_id": "state_graph", "edge_field_id": "state_graph"},
}

# Operator props that can carry StateBindingSpec references.
_OPERATOR_STATE_BINDING_PROPS: frozenset[str] = frozenset({"color", "alpha", "fill_alpha", "width"})

# Operator props whose change should trigger a line-plot refresh.
_GRID_SLICE_COMPUTE_PROPS: frozenset[str] = frozenset({"field_id", "geometry_id",
                                                        "axis_state_key", "position_state_key"})

# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RefreshTarget:
    kind: str
    view_id: str | None = None

    @classmethod
    def controls(cls) -> "RefreshTarget":
        return cls("controls")

    @classmethod
    def line_plot(cls, view_id: str) -> "RefreshTarget":
        return cls("line_plot", view_id)

    @classmethod
    def morphology(cls, view_id: str) -> "RefreshTarget":
        return cls("morphology", view_id)

    @classmethod
    def surface_visual(cls, view_id: str) -> "RefreshTarget":
        return cls("surface_visual", view_id)

    @classmethod
    def surface_style(cls, view_id: str) -> "RefreshTarget":
        return cls("surface_style", view_id)

    @classmethod
    def surface_axes_geometry(cls, view_id: str) -> "RefreshTarget":
        return cls("surface_axes_geometry", view_id)

    @classmethod
    def surface_axes_style(cls, view_id: str) -> "RefreshTarget":
        return cls("surface_axes_style", view_id)

    @classmethod
    def operator_overlay(cls, view_id: str) -> "RefreshTarget":
        return cls("operator_overlay", view_id)

    @classmethod
    def state_graph(cls, view_id: str) -> "RefreshTarget":
        return cls("state_graph", view_id)


RefreshTarget.CONTROLS = RefreshTarget.controls()


def _target_kind_counts(targets: set[RefreshTarget]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for target in targets:
        counts[target.kind] = counts.get(target.kind, 0) + 1
    return counts


class RefreshPlanner:
    def __init__(self, app_spec: AppSpec, active_layout):
        # app_spec: structural blueprint (views/operators) — working copy.
        # active_layout: zero-arg resolver for the live active LayoutSpec
        # (AppProjection-owned, so layout switches are reflected here).
        self.app_spec = app_spec
        self._active_layout = active_layout

    # ------------------------------------------------------------------
    # Full refresh

    def full_refresh_targets(self) -> set[RefreshTarget]:
        targets: set[RefreshTarget] = {RefreshTarget.CONTROLS}
        for panel in self._active_layout().panels:
            for view_id in panel.view_ids:
                view = self.app_spec.view_catalog.views.get(view_id)
                for kind in _VIEW_FULL_REFRESH_KINDS.get(type(view), ()):
                    targets.add(RefreshTarget(kind, view_id))
        return targets

    # ------------------------------------------------------------------
    # Incremental refresh routing

    def targets_for_view_patch(self, view_id: str, changed_props: set[str]) -> set[RefreshTarget]:
        view = self.app_spec.view_catalog.views.get(view_id)
        schema = _VIEW_PATCH_SCHEMA.get(type(view), {})
        targets: set[RefreshTarget] = set()
        for kind, props in schema.items():
            if props is None or changed_props & props:
                targets.add(RefreshTarget(kind, view_id))
        return targets

    def targets_for_state_change(self, state_key: str) -> set[RefreshTarget]:
        targets: set[RefreshTarget] = set()
        for panel in self._active_layout().panels:
            for view_id in panel.view_ids:
                view = self.app_spec.view_catalog.views.get(view_id)
                # Static prop → target mapping
                schema = _VIEW_STATE_BINDING_SCHEMA.get(type(view), {})
                for kind, props in schema.items():
                    if any(binding_key(getattr(view, p, None)) == state_key for p in props):
                        targets.add(RefreshTarget(kind, view_id))
                # LinePlotViewSpec: selectors dict + operator state keys
                if isinstance(view, LinePlotViewSpec):
                    if any(binding_key(v) == state_key for v in view.selectors.values()):
                        targets.add(RefreshTarget.line_plot(view_id))
                    if view.operator_id:
                        op = self.app_spec.view_catalog.operators.get(view.operator_id)
                        if isinstance(op, GridSliceOperatorSpec) and state_key in {
                            op.axis_state_key, op.position_state_key
                        }:
                            targets.add(RefreshTarget.line_plot(view_id))
                # Line/Bar reference lines: a level bound to this key moves the line.
                if isinstance(view, (LinePlotViewSpec, BarPlotViewSpec)):
                    if any(binding_key(marker.value) == state_key for marker in view.levels):
                        targets.add(RefreshTarget.line_plot(view_id))
                # SurfaceViewSpec: operator overlay state keys and style bindings
                if isinstance(view, SurfaceViewSpec):
                    for op_id in getattr(panel, "operator_ids", ()):
                        op = self.app_spec.view_catalog.operators.get(op_id)
                        if not isinstance(op, GridSliceOperatorSpec):
                            continue
                        if op.field_id != view.field_id or op.geometry_id not in {None, view.geometry_id}:
                            continue
                        if (
                            any(binding_key(getattr(op, p, None)) == state_key for p in _OPERATOR_STATE_BINDING_PROPS)
                            or state_key in {op.axis_state_key, op.position_state_key}
                        ):
                            targets.add(RefreshTarget.operator_overlay(view_id))
                            break
        return targets

    def targets_for_field_replace(self, field_id: str, coords_changed: bool = True) -> set[RefreshTarget]:
        targets: set[RefreshTarget] = set()
        for panel in self._active_layout().panels:
            for view_id in panel.view_ids:
                view = self.app_spec.view_catalog.views.get(view_id)
                # Schema-driven field-id prop checks
                for prop, kind in _VIEW_FIELD_ID_PROPS.get(type(view), {}).items():
                    if getattr(view, prop, None) == field_id:
                        targets.add(RefreshTarget(kind, view_id))
                # LinePlotViewSpec: operator-backed field reference
                if isinstance(view, LinePlotViewSpec) and view.operator_id:
                    op = self.app_spec.view_catalog.operators.get(view.operator_id)
                    if isinstance(op, GridSliceOperatorSpec) and op.field_id == field_id:
                        targets.add(RefreshTarget.line_plot(view_id))
                # SurfaceViewSpec: primary-field triggers + operator overlay
                if isinstance(view, SurfaceViewSpec):
                    if view.field_id == field_id:
                        targets.add(RefreshTarget.surface_visual(view_id))
                        if coords_changed or view.color_limits is None:
                            targets.add(RefreshTarget.surface_axes_geometry(view_id))
                    for op_id in getattr(panel, "operator_ids", ()):
                        op = self.app_spec.view_catalog.operators.get(op_id)
                        if (
                            isinstance(op, GridSliceOperatorSpec)
                            and op.field_id == field_id
                            and op.geometry_id in {None, view.geometry_id}
                        ):
                            targets.add(RefreshTarget.operator_overlay(view_id))
                            break
        return targets

    def targets_for_operator_patch(self, operator_id: str, changed_props: set[str]) -> set[RefreshTarget]:
        targets: set[RefreshTarget] = set()
        op = self.app_spec.view_catalog.operators.get(operator_id)
        for panel in self._active_layout().panels_of_kind(PANEL_KIND_VIEW_3D):
            if operator_id not in panel.operator_ids:
                continue
            for view_id in panel.view_ids:
                view = self.app_spec.view_catalog.views.get(view_id)
                if (
                    isinstance(view, SurfaceViewSpec)
                    and isinstance(op, GridSliceOperatorSpec)
                    and op.field_id == view.field_id
                    and op.geometry_id in {None, view.geometry_id}
                ):
                    targets.add(RefreshTarget.operator_overlay(view_id))
        for panel in self._active_layout().panels:
            for view_id in panel.view_ids:
                view = self.app_spec.view_catalog.views.get(view_id)
                if (
                    isinstance(view, LinePlotViewSpec)
                    and view.operator_id == operator_id
                    and changed_props & _GRID_SLICE_COMPUTE_PROPS
                ):
                    targets.add(RefreshTarget.line_plot(view_id))
        return targets


def resolve_value(value, state: dict[str, Any]):
    if isinstance(value, StateBindingSpec):
        return state.get(value.key)
    return value


def binding_key(value) -> str | None:
    if isinstance(value, StateBindingSpec):
        return value.key
    return None
