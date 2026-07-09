from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from compneurovis.core import (
    BarPlotViewSpec,
    GridSliceOperatorSpec,
    LinePlotViewSpec,
    MorphologyViewSpec,
    AppRef,
    app_ref,
    AppSpec,
    ValueBindingSpec,
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
# Only props that can actually be ValueBindingSpec references need to appear here.
_VIEW_VALUE_BINDING_SCHEMA: dict[type, dict[str, frozenset[str]]] = {
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

# Operator props that can carry ValueBindingSpec references.
_OPERATOR_VALUE_BINDING_PROPS: frozenset[str] = frozenset({"color", "alpha", "fill_alpha", "width"})

# Operator props whose change should trigger a line-plot refresh.
_GRID_SLICE_COMPUTE_PROPS: frozenset[str] = frozenset({"field_id", "geometry_id",
                                                        "axis_value_key", "position_value_key"})

# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RefreshTarget:
    kind: str
    view_id: str | AppRef | None = None

    @classmethod
    def controls(cls) -> "RefreshTarget":
        return cls("controls")

    @classmethod
    def line_plot(cls, view_id: str | AppRef) -> "RefreshTarget":
        return cls("line_plot", view_id)

    @classmethod
    def morphology(cls, view_id: str | AppRef) -> "RefreshTarget":
        return cls("morphology", view_id)

    @classmethod
    def surface_visual(cls, view_id: str | AppRef) -> "RefreshTarget":
        return cls("surface_visual", view_id)

    @classmethod
    def surface_style(cls, view_id: str | AppRef) -> "RefreshTarget":
        return cls("surface_style", view_id)

    @classmethod
    def surface_axes_geometry(cls, view_id: str | AppRef) -> "RefreshTarget":
        return cls("surface_axes_geometry", view_id)

    @classmethod
    def surface_axes_style(cls, view_id: str | AppRef) -> "RefreshTarget":
        return cls("surface_axes_style", view_id)

    @classmethod
    def operator_overlay(cls, view_id: str | AppRef) -> "RefreshTarget":
        return cls("operator_overlay", view_id)

    @classmethod
    def state_graph(cls, view_id: str | AppRef) -> "RefreshTarget":
        return cls("state_graph", view_id)


RefreshTarget.CONTROLS = RefreshTarget.controls()


def _target_kind_counts(targets: set[RefreshTarget]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for target in targets:
        counts[target.kind] = counts.get(target.kind, 0) + 1
    return counts


class RefreshPlanner:
    def __init__(self, app_spec: AppSpec, active_layout):
        self.app_spec = app_spec
        self._active_layout = active_layout

    def full_refresh_targets(self) -> set[RefreshTarget]:
        targets: set[RefreshTarget] = {RefreshTarget.CONTROLS}
        for panel in self._active_layout().panels:
            for view_id in panel.view_ids:
                view = self.app_spec.view(view_id)
                for kind in _VIEW_FULL_REFRESH_KINDS.get(type(view), ()):
                    targets.add(RefreshTarget(kind, view_id))
        return targets

    def targets_for_view_patch(self, view_id: str | AppRef, changed_props: set[str]) -> set[RefreshTarget]:
        view = self.app_spec.view(view_id)
        schema = _VIEW_PATCH_SCHEMA.get(type(view), {})
        targets: set[RefreshTarget] = set()
        for kind, props in schema.items():
            if props is None or changed_props & props:
                targets.add(RefreshTarget(kind, view_id))
        return targets

    def targets_for_value_change(self, value_key: str | AppRef) -> set[RefreshTarget]:
        targets: set[RefreshTarget] = set()
        for panel in self._active_layout().panels:
            for view_id in panel.view_ids:
                view_ref = app_ref(view_id)
                view = self.app_spec.view(view_ref)
                schema = _VIEW_VALUE_BINDING_SCHEMA.get(type(view), {})
                for kind, props in schema.items():
                    if any(_binding_matches(getattr(view, p, None), value_key, view_ref.fragment_id) for p in props):
                        targets.add(RefreshTarget(kind, view_id))
                if isinstance(view, LinePlotViewSpec):
                    if any(_binding_matches(v, value_key, view_ref.fragment_id) for v in view.selectors.values()):
                        targets.add(RefreshTarget.line_plot(view_id))
                    if view.operator_id:
                        op_ref = app_ref(view.operator_id, fragment_id=view_ref.fragment_id)
                        op = self.app_spec.operator(op_ref)
                        if isinstance(op, GridSliceOperatorSpec) and (
                            _value_key_matches(op.axis_value_key, value_key, view_ref.fragment_id)
                            or _value_key_matches(op.position_value_key, value_key, view_ref.fragment_id)
                        ):
                            targets.add(RefreshTarget.line_plot(view_id))
                if isinstance(view, (LinePlotViewSpec, BarPlotViewSpec)):
                    if any(_binding_matches(marker.value, value_key, view_ref.fragment_id) for marker in view.levels):
                        targets.add(RefreshTarget.line_plot(view_id))
                if isinstance(view, SurfaceViewSpec):
                    for op_id in getattr(panel, "operator_ids", ()):
                        op_ref = app_ref(op_id, fragment_id=view_ref.fragment_id)
                        op = self.app_spec.operator(op_ref)
                        if not isinstance(op, GridSliceOperatorSpec):
                            continue
                        if (
                            _ref(op.field_id, op_ref.fragment_id) != _ref(view.field_id, view_ref.fragment_id)
                            or _optional_ref(op.geometry_id, op_ref.fragment_id) not in {None, _optional_ref(view.geometry_id, view_ref.fragment_id)}
                        ):
                            continue
                        if (
                            any(_binding_matches(getattr(op, p, None), value_key, op_ref.fragment_id) for p in _OPERATOR_VALUE_BINDING_PROPS)
                            or _value_key_matches(op.axis_value_key, value_key, op_ref.fragment_id)
                            or _value_key_matches(op.position_value_key, value_key, op_ref.fragment_id)
                        ):
                            targets.add(RefreshTarget.operator_overlay(view_id))
                            break
        return targets

    def targets_for_field_replace(self, field_id: str | AppRef, coords_changed: bool = True) -> set[RefreshTarget]:
        field_ref = app_ref(field_id)
        targets: set[RefreshTarget] = set()
        for panel in self._active_layout().panels:
            for view_id in panel.view_ids:
                view_ref = app_ref(view_id)
                view = self.app_spec.view(view_ref)
                for prop, kind in _VIEW_FIELD_ID_PROPS.get(type(view), {}).items():
                    if _optional_ref(getattr(view, prop, None), view_ref.fragment_id) == field_ref:
                        targets.add(RefreshTarget(kind, view_id))
                if isinstance(view, LinePlotViewSpec) and view.operator_id:
                    op_ref = app_ref(view.operator_id, fragment_id=view_ref.fragment_id)
                    op = self.app_spec.operator(op_ref)
                    if isinstance(op, GridSliceOperatorSpec) and _ref(op.field_id, op_ref.fragment_id) == field_ref:
                        targets.add(RefreshTarget.line_plot(view_id))
                if isinstance(view, SurfaceViewSpec):
                    if _ref(view.field_id, view_ref.fragment_id) == field_ref:
                        targets.add(RefreshTarget.surface_visual(view_id))
                        if coords_changed or view.color_limits is None:
                            targets.add(RefreshTarget.surface_axes_geometry(view_id))
                    for op_id in getattr(panel, "operator_ids", ()):
                        op_ref = app_ref(op_id, fragment_id=view_ref.fragment_id)
                        op = self.app_spec.operator(op_ref)
                        if (
                            isinstance(op, GridSliceOperatorSpec)
                            and _ref(op.field_id, op_ref.fragment_id) == field_ref
                            and _optional_ref(op.geometry_id, op_ref.fragment_id) in {None, _optional_ref(view.geometry_id, view_ref.fragment_id)}
                        ):
                            targets.add(RefreshTarget.operator_overlay(view_id))
                            break
        return targets

    def targets_for_operator_patch(self, operator_id: str | AppRef, changed_props: set[str]) -> set[RefreshTarget]:
        op_ref = app_ref(operator_id)
        targets: set[RefreshTarget] = set()
        op = self.app_spec.operator(op_ref)
        for panel in self._active_layout().panels_of_kind(PANEL_KIND_VIEW_3D):
            if op_ref not in tuple(app_ref(item) for item in panel.operator_ids):
                continue
            for view_id in panel.view_ids:
                view_ref = app_ref(view_id)
                view = self.app_spec.view(view_ref)
                if (
                    isinstance(view, SurfaceViewSpec)
                    and isinstance(op, GridSliceOperatorSpec)
                    and _ref(op.field_id, op_ref.fragment_id) == _ref(view.field_id, view_ref.fragment_id)
                    and _optional_ref(op.geometry_id, op_ref.fragment_id) in {None, _optional_ref(view.geometry_id, view_ref.fragment_id)}
                ):
                    targets.add(RefreshTarget.operator_overlay(view_id))
        for panel in self._active_layout().panels:
            for view_id in panel.view_ids:
                view_ref = app_ref(view_id)
                view = self.app_spec.view(view_ref)
                if (
                    isinstance(view, LinePlotViewSpec)
                    and app_ref(view.operator_id, fragment_id=view_ref.fragment_id) == op_ref
                    and changed_props & _GRID_SLICE_COMPUTE_PROPS
                ):
                    targets.add(RefreshTarget.line_plot(view_id))
        return targets


def resolve_value(value, values: dict[Any, Any], fragment_id: str | None = None):
    if isinstance(value, ValueBindingSpec):
        if fragment_id is not None:
            scoped = app_ref(value.key, fragment_id=fragment_id)
            if scoped in values:
                return values.get(scoped)
        return values.get(value.key)
    return value


def binding_key(value, fragment_id: str | None = None) -> str | AppRef | None:
    if isinstance(value, ValueBindingSpec):
        return app_ref(value.key, fragment_id=fragment_id) if fragment_id is not None else value.key
    if isinstance(value, str) and fragment_id is not None:
        return app_ref(value, fragment_id=fragment_id)
    return value if isinstance(value, AppRef) else None


def _binding_matches(value, value_key: str | AppRef, fragment_id: str) -> bool:
    key = binding_key(value)
    return key is not None and _value_key_matches(key, value_key, fragment_id)


def _value_key_matches(local_key: str | AppRef | None, value_key: str | AppRef, fragment_id: str) -> bool:
    if local_key is None:
        return False
    scoped_key = app_ref(local_key, fragment_id=fragment_id)
    return value_key == local_key or value_key == scoped_key


def _ref(value: str | AppRef, fragment_id: str) -> AppRef:
    return app_ref(value, fragment_id=fragment_id)


def _optional_ref(value: str | AppRef | None, fragment_id: str) -> AppRef | None:
    if value is None:
        return None
    return app_ref(value, fragment_id=fragment_id)
