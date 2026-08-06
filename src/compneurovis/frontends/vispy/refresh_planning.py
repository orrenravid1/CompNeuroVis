from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from compneurovis.core import (
    ExtensionViewSpec,
    AppRef,
    app_ref,
    AppSpec,
)
from compneurovis.frontends.vispy.operator_adapters import (
    operator_adapter,
)
from compneurovis.frontends.vispy.render_config import view_render_config
from compneurovis.frontends.vispy.view_inputs.bindings import (
    _binding_matches,
    _contains_binding,
    _optional_ref,
    _ref,
)

# --- Schemas -----------------------------------------------------------------
#
# Refresh schemas are keyed by a view's declared kind, not its Python type.
# Shared-canvas 3-D contributors declare this internal schema through the public,
# complete register_scene_layer call. Ordinary extension QWidgets use the honest
# blanket "extension" target and may optimize internally during refresh.

# Refresh schemas are registered per view KIND -- see ``register_view_refresh_schema``.
# The planner ships with NONE baked in: built-in surface/morphology register from
# their own frontend modules (``view3d/surface.py``, ``view3d/morphology.py``) on
# exactly the same call a third party uses, so no view kind is privileged here.
#
# Maps view KIND → {target_kind → props that trigger it on a view patch}.
# None means "any changed prop triggers this target".
_VIEW_PATCH_SCHEMA: dict[str, dict[str, frozenset[str] | None]] = {}
# An unregistered kind (a plain extension) repaints its whole host.
_DEFAULT_PATCH_SCHEMA: dict[str, frozenset[str] | None] = {"extension": None}

# Maps view KIND -> {target_kind -> ValueOrBinding props} for binding-value checks.
# Only props that can actually be ValueBindingSpec references need to appear here.
_VIEW_VALUE_BINDING_SCHEMA: dict[str, dict[str, frozenset[str]]] = {}

# Maps view KIND → target kinds included in a full app spec refresh.
_VIEW_FULL_REFRESH_KINDS: dict[str, tuple[str, ...]] = {}
_DEFAULT_FULL_REFRESH_KINDS: tuple[str, ...] = ("extension",)

# Maps view KIND → {field-id prop name → target kind} for field-replace routing.
_VIEW_FIELD_ID_PROPS: dict[str, dict[str, str]] = {}

# Maps view KIND → hook(view, field_ref, coords_changed) -> set[RefreshTarget] for
# kinds whose field-replace routing is conditional (e.g. surface's axes geometry
# only rebuilds when coords change). A kind uses this OR the static field_id_props
# table above, never both.
_VIEW_FIELD_REPLACE_HOOKS: "dict[str, Callable[..., set[RefreshTarget]]]" = {}


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
    component registry internal prevents extension hosts from declaring target
    kinds the frontend cannot dispatch.

    ``field_replace_hook`` is the escape hatch for kinds whose field-replace routing
    is conditional and cannot be expressed by the static ``field_id_props`` table.
    """
    if patch is not None:
        _VIEW_PATCH_SCHEMA[kind] = patch
    if value_binding is not None:
        _VIEW_VALUE_BINDING_SCHEMA[kind] = value_binding
    if full_refresh is not None:
        _VIEW_FULL_REFRESH_KINDS[kind] = full_refresh
    if field_id_props is not None:
        _VIEW_FIELD_ID_PROPS[kind] = field_id_props
    if field_replace_hook is not None:
        _VIEW_FIELD_REPLACE_HOOKS[kind] = field_replace_hook

# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RefreshTarget:
    kind: str
    view_id: str | AppRef | None = None
    contribution_id: str | AppRef | None = None

    @classmethod
    def controls(cls) -> "RefreshTarget":
        return cls("controls")

    # No kind-specific factories (surface_visual/morphology/operator_overlay/...):
    # a target is just ``RefreshTarget(kind, view_id)``. Built-in and third-party
    # kinds construct theirs the same way, from their registered contributor.


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
    # case it depends on the field(s) + value keys that operator's output derives
    # from. Which those are is the operator's own knowledge, exposed by its
    # registered adapter -- the planner stays operator-kind agnostic. A plain
    # field input (no operator, no adapter) is its own single dependency.
    def _extension_field_deps(self, view: ExtensionViewSpec, fragment_id: str) -> list[str]:
        deps: list[str] = []
        for input_id in view.inputs.values():
            operator = self.app_spec.operator(app_ref(input_id, fragment_id=fragment_id))
            hook = getattr(operator_adapter(operator), "output_field_deps", None)
            deps.extend(hook(operator, fragment_id) if hook is not None else (input_id,))
        return deps

    def _extension_input_binds_value(
        self, view: ExtensionViewSpec, value_key: str | AppRef, fragment_id: str
    ) -> bool:
        for input_id in view.inputs.values():
            operator = self.app_spec.operator(app_ref(input_id, fragment_id=fragment_id))
            hook = getattr(operator_adapter(operator), "output_binds_value", None)
            if hook is not None and hook(operator, value_key, fragment_id):
                return True
        return False

    def _extension_references_operator(
        self, view: ExtensionViewSpec, op_ref: AppRef, fragment_id: str
    ) -> bool:
        return any(
            app_ref(input_id, fragment_id=fragment_id) == op_ref
            for input_id in view.inputs.values()
        )

    def _view(self, view_ref: str | AppRef):
        # Surface/morphology author as ExtensionViewSpec; rebuild the typed 3-D
        # render-config so the kind-keyed schema lookups + registered contributors
        # below see the resolved config. 2-D extension views and already-typed
        # render-configs pass through unchanged.
        return view_render_config(self.app_spec.view(view_ref))

    def _contribution(self, contribution_id, fragment_id: str):
        contribution_ref = app_ref(contribution_id, fragment_id=fragment_id)
        return contribution_ref, self.app_spec.visual_contribution(contribution_ref)

    def _contribution_field_deps(self, contribution, fragment_id: str) -> list[str]:
        deps: list[str] = []
        for input_id in contribution.inputs.values():
            operator = self.app_spec.operator(
                app_ref(input_id, fragment_id=fragment_id)
            )
            hook = getattr(operator_adapter(operator), "output_field_deps", None)
            deps.extend(
                hook(operator, fragment_id) if hook is not None else (input_id,)
            )
        return deps

    def _contribution_input_binds_value(
        self, contribution, value_key: str | AppRef, fragment_id: str
    ) -> bool:
        for input_id in contribution.inputs.values():
            operator = self.app_spec.operator(
                app_ref(input_id, fragment_id=fragment_id)
            )
            hook = getattr(operator_adapter(operator), "output_binds_value", None)
            if hook is not None and hook(operator, value_key, fragment_id):
                return True
        return False

    @staticmethod
    def _contribution_target(view_id, contribution_ref) -> RefreshTarget:
        return RefreshTarget(
            "visual_contribution",
            view_id,
            contribution_id=contribution_ref,
        )

    def full_refresh_targets(self) -> set[RefreshTarget]:
        targets: set[RefreshTarget] = {RefreshTarget.CONTROLS}
        for panel in self._active_layout().panels:
            for view_id in panel.view_ids:
                view = self._view(view_id)
                for kind in _VIEW_FULL_REFRESH_KINDS.get(view.kind, _DEFAULT_FULL_REFRESH_KINDS):
                    targets.add(RefreshTarget(kind, view_id))
            if panel.view_ids:
                view_ref = app_ref(panel.view_ids[0])
                for contribution_id in panel.contribution_ids:
                    contribution_ref, _ = self._contribution(
                        contribution_id, view_ref.fragment_id
                    )
                    targets.add(
                        self._contribution_target(
                            panel.view_ids[0], contribution_ref
                        )
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
                if isinstance(view, ExtensionViewSpec) and (
                    _contains_binding(view.properties, value_key, view_ref.fragment_id)
                    or self._extension_input_binds_value(view, value_key, view_ref.fragment_id)
                ):
                    targets.add(RefreshTarget("extension", view_id))
                if isinstance(authored_view, ExtensionViewSpec) and any(
                    app_ref(selection_id, fragment_id=view_ref.fragment_id)
                    == app_ref(value_key)
                    for selection_id in authored_view.selections.values()
                ):
                    for kind in _VIEW_FULL_REFRESH_KINDS.get(
                        view.kind,
                        _DEFAULT_FULL_REFRESH_KINDS,
                    ):
                        targets.add(RefreshTarget(kind, view_id))
            if panel.view_ids:
                view_ref = app_ref(panel.view_ids[0])
                for contribution_id in panel.contribution_ids:
                    contribution_ref, contribution = self._contribution(
                        contribution_id, view_ref.fragment_id
                    )
                    if contribution is None:
                        continue
                    selection_match = any(
                        app_ref(selection_id, fragment_id=view_ref.fragment_id)
                        == app_ref(value_key)
                        for selection_id in contribution.selections.values()
                    )
                    if (
                        _contains_binding(
                            contribution.properties,
                            value_key,
                            view_ref.fragment_id,
                        )
                        or self._contribution_input_binds_value(
                            contribution, value_key, view_ref.fragment_id
                        )
                        or selection_match
                    ):
                        targets.add(
                            self._contribution_target(
                                panel.view_ids[0], contribution_ref
                            )
                        )
        return targets

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
                if isinstance(view, ExtensionViewSpec) and any(
                    _ref(dep, view_ref.fragment_id) == field_ref
                    for dep in self._extension_field_deps(view, view_ref.fragment_id)
                ):
                    targets.add(RefreshTarget("extension", view_id))
            if panel.view_ids:
                view_ref = app_ref(panel.view_ids[0])
                for contribution_id in panel.contribution_ids:
                    contribution_ref, contribution = self._contribution(
                        contribution_id, view_ref.fragment_id
                    )
                    if contribution is not None and any(
                        _ref(dep, view_ref.fragment_id) == field_ref
                        for dep in self._contribution_field_deps(
                            contribution, view_ref.fragment_id
                        )
                    ):
                        targets.add(
                            self._contribution_target(
                                panel.view_ids[0], contribution_ref
                            )
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
                    if isinstance(
                        view, ExtensionViewSpec
                    ) and self._extension_references_operator(view, op_ref, view_ref.fragment_id):
                        targets.add(RefreshTarget("extension", view_id))
                if panel.view_ids:
                    view_ref = app_ref(panel.view_ids[0])
                    for contribution_id in panel.contribution_ids:
                        contribution_ref, contribution = self._contribution(
                            contribution_id, view_ref.fragment_id
                        )
                        if contribution is not None and any(
                            app_ref(input_id, fragment_id=view_ref.fragment_id)
                            == op_ref
                            for input_id in contribution.inputs.values()
                        ):
                            targets.add(
                                self._contribution_target(
                                    panel.view_ids[0], contribution_ref
                                )
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
            if contribution_ref in scoped_ids and panel.view_ids:
                targets.add(
                    self._contribution_target(
                        panel.view_ids[0], contribution_ref
                    )
                )
        return targets


