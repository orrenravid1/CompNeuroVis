from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields as dataclass_fields, is_dataclass
from typing import Any

from compneurovis.core import (
    ExtensionViewSpec,
    GridSliceOperatorSpec,
    MorphologyViewSpec,
    AppRef,
    app_ref,
    AppSpec,
    ValueBindingSpec,
    SurfaceViewSpec,
)
from compneurovis.core.app_spec import (
    PANEL_KIND_VIEW_3D,
)

# --- Schemas -----------------------------------------------------------------
#
# Refresh schemas are keyed by a view's declared ``kind`` (``view.kind``), not by
# its Python type. A third-party view kind can register its own schema (via
# ``register_view_refresh_schema``) and get the same surgical refresh a built-in
# gets; an unregistered kind falls back to a blanket host repaint. Adding a kind
# needs no planner method to change.

# Maps view KIND → {target_kind → props that trigger it on a view patch}.
# None means "any changed prop triggers this target".
_VIEW_PATCH_SCHEMA: dict[str, dict[str, frozenset[str] | None]] = {
    "morphology": {
        "morphology": None,
    },
    "surface": {
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
}
# An unregistered kind (a plain extension) repaints its whole host.
_DEFAULT_PATCH_SCHEMA: dict[str, frozenset[str] | None] = {"extension": None}

# Maps view KIND -> {target_kind -> ValueOrBinding props} for binding-value checks.
# Only props that can actually be ValueBindingSpec references need to appear here.
_VIEW_VALUE_BINDING_SCHEMA: dict[str, dict[str, frozenset[str]]] = {
    "morphology": {
        "morphology": frozenset({"background_color", "color_limits"}),
    },
    "surface": {
        "surface_visual":        frozenset({"field_id", "geometry_id"}),
        "surface_style":         frozenset({"color_map", "color_limits", "color_by",
                                            "surface_color", "surface_shading", "surface_alpha",
                                            "background_color"}),
        "surface_axes_geometry": frozenset({"render_axes", "axes_in_middle",
                                            "tick_count", "tick_length_scale"}),
        "surface_axes_style":    frozenset({"tick_label_size", "axis_label_size",
                                            "axis_color", "text_color", "axis_alpha"}),
    },
}

# Maps view KIND → target kinds included in a full app spec refresh.
_VIEW_FULL_REFRESH_KINDS: dict[str, tuple[str, ...]] = {
    "morphology":  ("morphology",),
    "surface":     ("surface_visual", "surface_axes_geometry", "operator_overlay"),
}
_DEFAULT_FULL_REFRESH_KINDS: tuple[str, ...] = ("extension",)

# Maps view KIND → {field-id prop name → target kind} for field-replace routing.
# Surface omitted: its conditional axes-geometry logic is handled inline.
_VIEW_FIELD_ID_PROPS: dict[str, dict[str, str]] = {
    "morphology": {"color_field_id": "morphology"},
}


def register_view_refresh_schema(
    kind: str,
    *,
    patch: dict[str, frozenset[str] | None] | None = None,
    value_binding: dict[str, frozenset[str]] | None = None,
    full_refresh: tuple[str, ...] | None = None,
    field_id_props: dict[str, str] | None = None,
) -> None:
    """Register a fine-grained refresh schema for a view ``kind``.

    Any view kind -- built-in or third-party -- can declare which changes route to
    which refresh targets, in place of the blanket host repaint an unregistered
    kind falls back to. Surgical refresh on the same footing as the built-ins, no
    privileged view type required.
    """
    if patch is not None:
        _VIEW_PATCH_SCHEMA[kind] = patch
    if value_binding is not None:
        _VIEW_VALUE_BINDING_SCHEMA[kind] = value_binding
    if full_refresh is not None:
        _VIEW_FULL_REFRESH_KINDS[kind] = full_refresh
    if field_id_props is not None:
        _VIEW_FIELD_ID_PROPS[kind] = field_id_props

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

    # --- operator inputs: an extension view input may name an operator, in which
    # case it depends on that operator's source field + value keys. Expanding
    # those here keeps operators "just a data source" for the consuming view --
    # no view-type knowledge, works for any extension kind.
    def _extension_field_deps(self, view: ExtensionViewSpec, fragment_id: str) -> list[str]:
        deps: list[str] = []
        for input_id in view.inputs.values():
            operator = self.app_spec.operator(app_ref(input_id, fragment_id=fragment_id))
            deps.append(
                operator.field_id if isinstance(operator, GridSliceOperatorSpec) else input_id
            )
        return deps

    def _extension_input_binds_value(
        self, view: ExtensionViewSpec, value_key: str | AppRef, fragment_id: str
    ) -> bool:
        for input_id in view.inputs.values():
            operator = self.app_spec.operator(app_ref(input_id, fragment_id=fragment_id))
            if isinstance(operator, GridSliceOperatorSpec) and (
                _value_key_matches(operator.axis_value_key, value_key, fragment_id)
                or _value_key_matches(operator.position_value_key, value_key, fragment_id)
            ):
                return True
        return False

    def _extension_references_operator(
        self, view: ExtensionViewSpec, op_ref: AppRef, fragment_id: str
    ) -> bool:
        return any(
            app_ref(input_id, fragment_id=fragment_id) == op_ref
            for input_id in view.inputs.values()
        )

    def full_refresh_targets(self) -> set[RefreshTarget]:
        targets: set[RefreshTarget] = {RefreshTarget.CONTROLS}
        for panel in self._active_layout().panels:
            for view_id in panel.view_ids:
                view = self.app_spec.view(view_id)
                for kind in _VIEW_FULL_REFRESH_KINDS.get(view.kind, _DEFAULT_FULL_REFRESH_KINDS):
                    targets.add(RefreshTarget(kind, view_id))
        return targets

    def targets_for_view_patch(self, view_id: str | AppRef, changed_props: set[str]) -> set[RefreshTarget]:
        view = self.app_spec.view(view_id)
        schema = _VIEW_PATCH_SCHEMA.get(view.kind, _DEFAULT_PATCH_SCHEMA)
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
                schema = _VIEW_VALUE_BINDING_SCHEMA.get(view.kind, {})
                for kind, props in schema.items():
                    if any(_binding_matches(getattr(view, p, None), value_key, view_ref.fragment_id) for p in props):
                        targets.add(RefreshTarget(kind, view_id))
                if isinstance(view, ExtensionViewSpec) and (
                    _contains_binding(view.properties, value_key, view_ref.fragment_id)
                    or self._extension_input_binds_value(view, value_key, view_ref.fragment_id)
                ):
                    targets.add(RefreshTarget("extension", view_id))
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
                for prop, kind in _VIEW_FIELD_ID_PROPS.get(view.kind, {}).items():
                    if _optional_ref(getattr(view, prop, None), view_ref.fragment_id) == field_ref:
                        targets.add(RefreshTarget(kind, view_id))
                if isinstance(view, ExtensionViewSpec) and any(
                    _ref(dep, view_ref.fragment_id) == field_ref
                    for dep in self._extension_field_deps(view, view_ref.fragment_id)
                ):
                    targets.add(RefreshTarget("extension", view_id))
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
                    isinstance(view, ExtensionViewSpec)
                    and self._extension_references_operator(view, op_ref, view_ref.fragment_id)
                    and changed_props & _GRID_SLICE_COMPUTE_PROPS
                ):
                    targets.add(RefreshTarget("extension", view_id))
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


def _contains_binding(value: Any, value_key: str | AppRef, fragment_id: str) -> bool:
    # A binding leaf (ValueBindingSpec / AppRef) is itself a dataclass, so match
    # it *before* the dataclass-descent branch -- otherwise we'd walk into its
    # raw ``key`` string instead of treating it as the binding it is.
    if _binding_matches(value, value_key, fragment_id):
        return True
    if isinstance(value, Mapping):
        return any(
            _contains_binding(item, value_key, fragment_id)
            for item in value.values()
        )
    if isinstance(value, (tuple, list)):
        return any(_contains_binding(item, value_key, fragment_id) for item in value)
    if is_dataclass(value) and not isinstance(value, type):
        # Descend into dataclass-valued properties (e.g. reference-line markers,
        # whose ``value`` may itself be a binding) so a bound field nested in a
        # structured property still triggers a refresh -- generically, without
        # this planner knowing the dataclass's type.
        return any(
            _contains_binding(getattr(value, f.name), value_key, fragment_id)
            for f in dataclass_fields(value)
        )
    return False


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
