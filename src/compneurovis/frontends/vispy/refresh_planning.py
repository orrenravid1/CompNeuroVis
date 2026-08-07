from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping

from compneurovis.core import (
    ViewSpec,
    AppRef,
    app_ref,
    AppSpec,
)
from compneurovis.frontends.vispy.registries.operators import (
    operator_adapter,
)
from compneurovis.frontends.vispy.registries.render_configs import view_render_config
from compneurovis.frontends.vispy.bindings import (
    _binding_matches,
    _contains_binding,
    _optional_ref,
    _ref,
)

# --- Schemas -----------------------------------------------------------------
#
# Refresh schemas are keyed by a view's declared kind, not its Python type.
# Shared-canvas 3-D contributors declare this internal schema through the public,
# complete register_scene_layer call. Ordinary views use the neutral blanket
# "view" target and may optimize internally during refresh.

# Refresh schemas are registered per view KIND -- see ``register_view_refresh_schema``.
# The planner ships with NONE baked in: built-in surface/morphology register from
# their own frontend modules (``view3d/surface.py``, ``view3d/morphology.py``) on
# exactly the same call a third party uses, so no view kind is privileged here.
#
# Maps view KIND → {target_kind → props that trigger it on a view patch}.
# None means "any changed prop triggers this target".
_VIEW_PATCH_SCHEMA: dict[
    str, Mapping[str, frozenset[str] | None]
] = {}
# An unregistered kind repaints its whole view.
_DEFAULT_PATCH_SCHEMA: dict[str, frozenset[str] | None] = {"view": None}

# Maps view KIND -> {target_kind -> ValueOrBinding props} for binding-value checks.
# Only props that can actually be ValueBindingSpec references need to appear here.
_VIEW_VALUE_BINDING_SCHEMA: dict[str, Mapping[str, frozenset[str]]] = {}

# Maps view KIND → target kinds included in a full app spec refresh.
_VIEW_FULL_REFRESH_KINDS: dict[str, tuple[str, ...]] = {}
_DEFAULT_FULL_REFRESH_KINDS: tuple[str, ...] = ("view",)

# Maps view KIND → {field-id prop name → target kind} for field-replace routing.
_VIEW_FIELD_ID_PROPS: dict[str, Mapping[str, str]] = {}

# Maps view KIND → hook(view, field_ref, coords_changed) -> set[RefreshTarget] for
# kinds whose field-replace routing is conditional (e.g. surface's axes geometry
# only rebuilds when coords change). A kind uses this OR the static field_id_props
# table above, never both.
_VIEW_FIELD_REPLACE_HOOKS: "dict[str, Callable[..., set[RefreshTarget]]]" = {}


@dataclass(frozen=True, slots=True)
class _ViewRefreshRegistration:
    patch: Mapping[str, frozenset[str] | None] | None
    value_binding: Mapping[str, frozenset[str]] | None
    full_refresh: tuple[str, ...] | None
    field_id_props: Mapping[str, str] | None
    field_replace_hook: "Callable[..., set[RefreshTarget]] | None"


_VIEW_REFRESH_REGISTRATIONS: dict[str, _ViewRefreshRegistration] = {}


def _frozen_schema(
    schema: Mapping[str, Any] | None,
    *,
    allow_none: bool,
) -> Mapping[str, Any] | None:
    if schema is None:
        return None
    copied: dict[str, Any] = {}
    for target, properties in schema.items():
        if properties is None:
            if not allow_none:
                raise TypeError(f"Refresh target {target!r} requires a property set")
            copied[target] = None
        else:
            copied[target] = frozenset(properties)
    return MappingProxyType(copied)


def _prepare_view_refresh_schema_registration(
    *,
    patch: Mapping[str, frozenset[str] | None] | None,
    value_binding: Mapping[str, frozenset[str]] | None,
    full_refresh: tuple[str, ...] | None,
    field_id_props: Mapping[str, str] | None,
    field_replace_hook: "Callable[..., set[RefreshTarget]] | None",
) -> _ViewRefreshRegistration:
    return _ViewRefreshRegistration(
        patch=_frozen_schema(patch, allow_none=True),
        value_binding=_frozen_schema(value_binding, allow_none=False),
        full_refresh=None if full_refresh is None else tuple(full_refresh),
        field_id_props=(
            None
            if field_id_props is None
            else MappingProxyType(dict(field_id_props))
        ),
        field_replace_hook=field_replace_hook,
    )


def _validate_view_refresh_schema_registration(
    kind: str,
    registration: _ViewRefreshRegistration,
) -> str:
    normalized = str(kind).strip()
    if not normalized:
        raise ValueError("View refresh-schema kind cannot be empty")
    existing = _VIEW_REFRESH_REGISTRATIONS.get(normalized)
    if existing is not None and existing != registration:
        raise ValueError(
            f"VisPy view refresh schema {normalized!r} is already registered"
        )
    return normalized


def _commit_view_refresh_schema_registration(
    kind: str,
    registration: _ViewRefreshRegistration,
) -> None:
    _VIEW_REFRESH_REGISTRATIONS[kind] = registration
    destinations = (
        (_VIEW_PATCH_SCHEMA, registration.patch),
        (_VIEW_VALUE_BINDING_SCHEMA, registration.value_binding),
        (_VIEW_FULL_REFRESH_KINDS, registration.full_refresh),
        (_VIEW_FIELD_ID_PROPS, registration.field_id_props),
        (_VIEW_FIELD_REPLACE_HOOKS, registration.field_replace_hook),
    )
    for destination, value in destinations:
        if value is None:
            destination.pop(kind, None)
        else:
            destination[kind] = value


def register_view_refresh_schema(
    kind: str,
    *,
    patch: dict[str, frozenset[str] | None] | None = None,
    value_binding: dict[str, frozenset[str]] | None = None,
    full_refresh: tuple[str, ...] | None = None,
    field_id_props: dict[str, str] | None = None,
    field_replace_hook: "Callable[..., set[RefreshTarget]] | None" = None,
) -> None:
    """Register internal fine-grained routing for a shared-canvas 3-D view.

    Public authors provide this data through ``register_scene_layer``; keeping this
    component registry internal prevents standalone hosts from declaring target
    kinds the frontend cannot dispatch.

    ``field_replace_hook`` is the escape hatch for kinds whose field-replace routing
    is conditional and cannot be expressed by the static ``field_id_props`` table.
    """
    registration = _prepare_view_refresh_schema_registration(
        patch=patch,
        value_binding=value_binding,
        full_refresh=full_refresh,
        field_id_props=field_id_props,
        field_replace_hook=field_replace_hook,
    )
    normalized = _validate_view_refresh_schema_registration(kind, registration)
    _commit_view_refresh_schema_registration(normalized, registration)

# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RefreshTarget:
    kind: str
    view_id: str | AppRef | None = None
    contribution_id: str | AppRef | None = None
    panel_id: str | None = None

    @classmethod
    def controls(cls, panel_id: str) -> "RefreshTarget":
        return cls("controls", panel_id=panel_id)

    @classmethod
    def view(cls, view_id: str | AppRef) -> "RefreshTarget":
        return cls("view", view_id=view_id)

    # No kind-specific factories (surface_visual/morphology/operator_overlay/...):
    # a target is just ``RefreshTarget(kind, view_id)``. Built-in and third-party
    # kinds construct theirs the same way, from their registered contributor.

def _target_kind_counts(targets: set[RefreshTarget]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for target in targets:
        counts[target.kind] = counts.get(target.kind, 0) + 1
    return counts


class RefreshPlanner:
    def __init__(
        self,
        app_spec: AppSpec | Callable[[], AppSpec],
        active_layout,
    ):
        self._app_spec = app_spec
        self._active_layout = active_layout

    @property
    def app_spec(self) -> AppSpec:
        source = self._app_spec
        return source() if callable(source) else source

    # --- operator inputs: a view input may name an operator, in which
    # case it depends on the field(s) + value keys that operator's output derives
    # from. Which those are is the operator's own knowledge, exposed by its
    # registered adapter -- the planner stays operator-kind agnostic. A plain
    # field input (no operator, no adapter) is its own single dependency.
    def _data_field_deps(
        self,
        source_id: str | AppRef,
        fragment_id: str,
        *,
        _path: tuple[AppRef, ...] = (),
    ) -> list[str | AppRef]:
        source_ref = app_ref(source_id, fragment_id=fragment_id)
        if source_ref in _path:
            return []
        operator = self.app_spec.operator(source_ref)
        if operator is None:
            return [source_ref]
        hook = getattr(operator_adapter(operator), "output_field_deps", None)
        if hook is None:
            return []
        deps: list[str | AppRef] = []
        for dependency in hook(operator, source_ref.fragment_id):
            deps.extend(
                self._data_field_deps(
                    dependency,
                    source_ref.fragment_id,
                    _path=(*_path, source_ref),
                )
            )
        return deps

    def _view_field_deps(
        self, view: ViewSpec, fragment_id: str
    ) -> list[str | AppRef]:
        return [
            dependency
            for input_id in view.inputs.values()
            for dependency in self._data_field_deps(input_id, fragment_id)
        ]

    def _data_input_binds_value(
        self,
        source_id: str | AppRef,
        value_key: str | AppRef,
        fragment_id: str,
        *,
        _path: tuple[AppRef, ...] = (),
    ) -> bool:
        source_ref = app_ref(source_id, fragment_id=fragment_id)
        if source_ref in _path:
            return False
        operator = self.app_spec.operator(source_ref)
        if operator is None:
            return False
        adapter = operator_adapter(operator)
        hook = getattr(adapter, "output_binds_value", None)
        if hook is not None and hook(
            operator,
            value_key,
            source_ref.fragment_id,
        ):
            return True
        deps_hook = getattr(adapter, "output_field_deps", None)
        return deps_hook is not None and any(
            self._data_input_binds_value(
                dependency,
                value_key,
                source_ref.fragment_id,
                _path=(*_path, source_ref),
            )
            for dependency in deps_hook(operator, source_ref.fragment_id)
        )

    def _view_input_binds_value(
        self, view: ViewSpec, value_key: str | AppRef, fragment_id: str
    ) -> bool:
        return any(
            self._data_input_binds_value(input_id, value_key, fragment_id)
            for input_id in view.inputs.values()
        )

    def _data_references_operator(
        self,
        source_id: str | AppRef,
        op_ref: AppRef,
        fragment_id: str,
        *,
        _path: tuple[AppRef, ...] = (),
    ) -> bool:
        source_ref = app_ref(source_id, fragment_id=fragment_id)
        if source_ref == op_ref:
            return True
        if source_ref in _path:
            return False
        operator = self.app_spec.operator(source_ref)
        return operator is not None and any(
            self._data_references_operator(
                dependency,
                op_ref,
                source_ref.fragment_id,
                _path=(*_path, source_ref),
            )
            for dependency in operator.inputs.values()
        )

    def _view_references_operator(
        self, view: ViewSpec, op_ref: AppRef, fragment_id: str
    ) -> bool:
        return any(
            self._data_references_operator(
                input_id,
                op_ref,
                fragment_id,
            )
            for input_id in view.inputs.values()
        )

    def _view(self, view_ref: str | AppRef):
        # Surface/morphology author as ViewSpec; rebuild the typed 3-D
        # render-config so the kind-keyed schema lookups + registered contributors
        # below see the resolved config. 2-D views and already-typed
        # render-configs pass through unchanged.
        return view_render_config(self.app_spec.view(view_ref))

    def _contribution(self, contribution_id):
        contribution_ref = app_ref(contribution_id)
        return contribution_ref, self.app_spec.visual_contribution(contribution_ref)

    def _contribution_field_deps(
        self, contribution, fragment_id: str
    ) -> list[str | AppRef]:
        return [
            dependency
            for input_id in contribution.inputs.values()
            for dependency in self._data_field_deps(input_id, fragment_id)
        ]

    def _contribution_input_binds_value(
        self, contribution, value_key: str | AppRef, fragment_id: str
    ) -> bool:
        return any(
            self._data_input_binds_value(
                input_id,
                value_key,
                fragment_id,
            )
            for input_id in contribution.inputs.values()
        )

    @staticmethod
    def _contribution_target(panel_id: str, contribution_ref) -> RefreshTarget:
        return RefreshTarget(
            "visual_contribution",
            contribution_id=contribution_ref,
            panel_id=panel_id,
        )

    def full_refresh_targets(
        self, *, panel_ids: set[str] | None = None
    ) -> set[RefreshTarget]:
        targets: set[RefreshTarget] = set()
        for panel in self._active_layout().panels:
            if panel_ids is not None and panel.id not in panel_ids:
                continue
            if panel.control_ids or panel.action_ids:
                targets.add(RefreshTarget.controls(panel.id))
            for view_id in panel.view_ids:
                view = self._view(view_id)
                for kind in _VIEW_FULL_REFRESH_KINDS.get(view.kind, _DEFAULT_FULL_REFRESH_KINDS):
                    targets.add(RefreshTarget(kind, view_id))
            for contribution_id in panel.contribution_ids:
                contribution_ref, _ = self._contribution(contribution_id)
                targets.add(
                    self._contribution_target(panel.id, contribution_ref)
                )
        return targets

    def targets_for_view_patch(self, view_id: str | AppRef, changed_props: set[str]) -> set[RefreshTarget]:
        view = self._view(view_id)
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
                view = self._view(view_ref)
                authored_view = self.app_spec.view(view_ref)
                schema = _VIEW_VALUE_BINDING_SCHEMA.get(view.kind, {})
                for kind, props in schema.items():
                    if any(_binding_matches(getattr(view, p, None), value_key, view_ref.fragment_id) for p in props):
                        targets.add(RefreshTarget(kind, view_id))
                if isinstance(view, ViewSpec) and (
                    _contains_binding(view.properties, value_key, view_ref.fragment_id)
                    or self._view_input_binds_value(view, value_key, view_ref.fragment_id)
                ):
                    targets.add(RefreshTarget.view(view_id))
                if isinstance(authored_view, ViewSpec) and any(
                    app_ref(selection_id, fragment_id=view_ref.fragment_id)
                    == app_ref(value_key)
                    for selection_id in authored_view.selections.values()
                ):
                    for kind in _VIEW_FULL_REFRESH_KINDS.get(
                        view.kind,
                        _DEFAULT_FULL_REFRESH_KINDS,
                    ):
                        targets.add(RefreshTarget(kind, view_id))
            for contribution_id in panel.contribution_ids:
                contribution_ref, contribution = self._contribution(contribution_id)
                if contribution is None:
                    continue
                fragment_id = contribution_ref.fragment_id
                selection_match = any(
                    app_ref(selection_id, fragment_id=fragment_id)
                    == app_ref(value_key)
                    for selection_id in contribution.selections.values()
                )
                if (
                    _contains_binding(
                        contribution.properties,
                        value_key,
                        fragment_id,
                    )
                    or self._contribution_input_binds_value(
                        contribution, value_key, fragment_id
                    )
                    or selection_match
                ):
                    targets.add(
                        self._contribution_target(panel.id, contribution_ref)
                    )
        return targets

    def targets_for_control_value(
        self, value_key: str | AppRef
    ) -> set[RefreshTarget]:
        value_ref = app_ref(value_key)
        targets: set[RefreshTarget] = set()
        for panel in self._active_layout().panels:
            for control_id in panel.control_ids:
                control_ref = app_ref(control_id)
                control = self.app_spec.control(control_ref)
                if (
                    control is not None
                    and app_ref(
                        control.resolved_value_key(),
                        fragment_id=control_ref.fragment_id,
                    )
                    == value_ref
                ):
                    targets.add(RefreshTarget.controls(panel.id))
                    break
        return targets

    def targets_for_control_patch(
        self, control_id: str | AppRef
    ) -> set[RefreshTarget]:
        control_ref = app_ref(control_id)
        return {
            RefreshTarget.controls(panel.id)
            for panel in self._active_layout().panels
            if any(app_ref(item) == control_ref for item in panel.control_ids)
        }

    def targets_for_field_replace(self, field_id: str | AppRef, coords_changed: bool = True) -> set[RefreshTarget]:
        field_ref = app_ref(field_id)
        targets: set[RefreshTarget] = set()
        for panel in self._active_layout().panels:
            for view_id in panel.view_ids:
                view_ref = app_ref(view_id)
                view = self._view(view_ref)
                for prop, kind in _VIEW_FIELD_ID_PROPS.get(view.kind, {}).items():
                    if _optional_ref(getattr(view, prop, None), view_ref.fragment_id) == field_ref:
                        targets.add(RefreshTarget(kind, view_id))
                hook = _VIEW_FIELD_REPLACE_HOOKS.get(view.kind)
                if hook is not None:
                    targets |= hook(RefreshTarget, view, view_id, field_ref, view_ref.fragment_id, coords_changed)
                if isinstance(view, ViewSpec) and any(
                    _ref(dep, view_ref.fragment_id) == field_ref
                    for dep in self._view_field_deps(view, view_ref.fragment_id)
                ):
                    targets.add(RefreshTarget.view(view_id))
            for contribution_id in panel.contribution_ids:
                contribution_ref, contribution = self._contribution(contribution_id)
                fragment_id = contribution_ref.fragment_id
                if contribution is not None and any(
                    _ref(dep, fragment_id) == field_ref
                    for dep in self._contribution_field_deps(
                        contribution, fragment_id
                    )
                ):
                    targets.add(
                        self._contribution_target(panel.id, contribution_ref)
                    )
        return targets

    def targets_for_operator_patch(self, operator_id: str | AppRef, changed_props: set[str]) -> set[RefreshTarget]:
        op_ref = app_ref(operator_id)
        targets: set[RefreshTarget] = set()
        op = self.app_spec.operator(op_ref)
        # A view consuming this operator as a data input refreshes only when the
        # patch changed a prop that alters the operator's *output* -- which props
        # those are is the operator's own knowledge, exposed via ``affects_output``.
        affects_output = getattr(operator_adapter(op), "affects_output", None)
        output_changed = affects_output(changed_props) if affects_output else True
        if output_changed:
            for panel in self._active_layout().panels:
                for view_id in panel.view_ids:
                    view_ref = app_ref(view_id)
                    view = self._view(view_ref)
                    authored_view = self.app_spec.view(view_ref)
                    if isinstance(
                        authored_view, ViewSpec
                    ) and self._view_references_operator(
                        authored_view, op_ref, view_ref.fragment_id
                    ):
                        for kind in _VIEW_FULL_REFRESH_KINDS.get(
                            view.kind, _DEFAULT_FULL_REFRESH_KINDS
                        ):
                            targets.add(RefreshTarget(kind, view_id))
                for contribution_id in panel.contribution_ids:
                    contribution_ref, contribution = self._contribution(contribution_id)
                    fragment_id = contribution_ref.fragment_id
                    if contribution is not None and any(
                        self._data_references_operator(
                            input_id,
                            op_ref,
                            fragment_id,
                        )
                        for input_id in contribution.inputs.values()
                    ):
                        targets.add(
                            self._contribution_target(panel.id, contribution_ref)
                        )
        return targets

    def targets_for_visual_contribution_patch(
        self, contribution_id: str | AppRef
    ) -> set[RefreshTarget]:
        contribution_ref = app_ref(contribution_id)
        targets: set[RefreshTarget] = set()
        for panel in self._active_layout().panels:
            scoped_ids = {
                app_ref(item, fragment_id=contribution_ref.fragment_id)
                for item in panel.contribution_ids
            }
            if contribution_ref in scoped_ids:
                targets.add(
                    self._contribution_target(panel.id, contribution_ref)
                )
        return targets


