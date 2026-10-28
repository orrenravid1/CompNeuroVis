from __future__ import annotations

from compneurovis.core.app_spec import (
    AppFragmentSpec,
    AppSpec,
    LayoutSpec,
    PanelSpec,
)
from compneurovis.core.references import AppRef, app_ref, validate_local_id


def validate_app_spec(app_spec: AppSpec) -> None:
    """Validate blueprint integrity without normalizing or mutating it."""
    for fragment_id, fragment in app_spec.fragments.items():
        _validate_fragment_dependencies(app_spec, fragment_id, fragment)
    for layout_id, layout in app_spec.layout_catalog.layouts.items():
        _validate_layout(app_spec, layout_id, layout)
    for fragment_id, fragment in app_spec.fragments.items():
        for layout_id, layout in fragment.layout_catalog.layouts.items():
            _validate_layout(
                app_spec,
                f"{fragment_id}:{layout_id}",
                layout,
                fragment_id=fragment_id,
            )


def _validate_fragment_dependencies(
    app_spec: AppSpec,
    fragment_id: str,
    fragment: AppFragmentSpec,
) -> None:
    for view in fragment.view_catalog.views.values():
        for role, source_id in view.inputs.items():
            source_ref = app_ref(source_id, fragment_id=fragment_id)
            if (
                app_spec.field_spec(source_ref) is None
                and app_spec.operator(source_ref) is None
            ):
                raise ValueError(
                    f"View {source_ref.fragment_id}:{view.id} input "
                    f"{role!r} references unknown data source {source_id!r}"
                )
        for role, geometry_id in view.geometries.items():
            geometry_ref = app_ref(geometry_id, fragment_id=fragment_id)
            if app_spec.geometry(geometry_ref) is None:
                raise ValueError(
                    f"View {geometry_ref.fragment_id}:{view.id} geometry "
                    f"{role!r} references unknown geometry {geometry_id!r}"
                )
        for role, selection_id in view.selections.items():
            selection_ref = app_ref(selection_id, fragment_id=fragment_id)
            selection = app_spec.selection(selection_ref)
            if selection is None:
                raise ValueError(
                    f"View {selection_ref.fragment_id}:{view.id} selection "
                    f"{role!r} references unknown selection {selection_id!r}"
                )
            selection_target_ref = app_ref(
                selection.target_id,
                fragment_id=selection_ref.fragment_id,
            )
            declared_targets = (
                {
                    app_ref(geometry_id, fragment_id=fragment_id)
                    for geometry_id in view.geometries.values()
                }
                if selection.target_type == "geometry"
                else {
                    app_ref(target_id, fragment_id=fragment_id)
                    for target_id in view.hit_targets.values()
                }
            )
            if selection_target_ref not in declared_targets:
                raise ValueError(
                    f"View {selection_ref.fragment_id}:{view.id} selection "
                    f"{role!r} belongs to {selection.target_type} "
                    f"{selection.target_id!r}, "
                    "which the view does not declare"
                )
        for role, target_id in view.hit_targets.items():
            target_ref = app_ref(target_id, fragment_id=fragment_id)
            target = app_spec.hit_target(target_ref)
            if target is None:
                raise ValueError(
                    f"View {target_ref.fragment_id}:{view.id} hit target "
                    f"{role!r} references unknown target {target_id!r}"
                )
        for role, interaction_id in view.clicks.items():
            interaction_ref = app_ref(interaction_id, fragment_id=fragment_id)
            interaction = app_spec.click(interaction_ref)
            if interaction is None:
                raise ValueError(
                    f"View {interaction_ref.fragment_id}:{view.id} click "
                    f"{role!r} references unknown interaction {interaction_id!r}"
                )
            click_target_ref = app_ref(
                interaction.hit_target_id,
                fragment_id=interaction_ref.fragment_id,
            )
            view_target_id = view.hit_targets.get(role)
            view_target_ref = (
                None
                if view_target_id is None
                else app_ref(view_target_id, fragment_id=fragment_id)
            )
            if click_target_ref != view_target_ref:
                raise ValueError(
                    f"View {interaction_ref.fragment_id}:{view.id} click "
                    f"{role!r} belongs to hit target {interaction.hit_target_id!r}, "
                    f"not the view role's target {view_target_id!r}"
                )
            if interaction.geometry_scope_id is not None:
                scope_ref = app_ref(
                    interaction.geometry_scope_id,
                    fragment_id=interaction_ref.fragment_id,
                )
                declared_geometry_refs = {
                    app_ref(geometry_id, fragment_id=fragment_id)
                    for geometry_id in view.geometries.values()
                }
                if scope_ref not in declared_geometry_refs:
                    raise ValueError(
                        f"View {interaction_ref.fragment_id}:{view.id} click "
                        f"{role!r} geometry scope {interaction.geometry_scope_id!r} "
                        "is not one of the view's declared geometries"
                    )

    for selection in fragment.interactions.selections.values():
        target_ref = app_ref(selection.target_id, fragment_id=fragment_id)
        target = (
            app_spec.geometry(target_ref)
            if selection.target_type == "geometry"
            else app_spec.hit_target(target_ref)
        )
        if target is None:
            raise ValueError(
                f"Selection {fragment_id}:{selection.id} references unknown "
                f"{selection.target_type} {selection.target_id!r}"
            )

    for interaction in fragment.interactions.clicks.values():
        target_ref = app_ref(interaction.hit_target_id, fragment_id=fragment_id)
        target = app_spec.hit_target(target_ref)
        if target is None:
            raise ValueError(
                f"Click {fragment_id}:{interaction.id} references unknown "
                f"hit target {interaction.hit_target_id!r}"
            )
        scope_ref = (
            None
            if interaction.geometry_scope_id is None
            else app_ref(interaction.geometry_scope_id, fragment_id=fragment_id)
        )
        if scope_ref is not None and app_spec.geometry(scope_ref) is None:
            raise ValueError(
                f"Click {fragment_id}:{interaction.id} references unknown result "
                f"scope geometry {interaction.geometry_scope_id!r}"
            )
        if interaction.selection_id is None:
            continue
        selection_ref = app_ref(
            interaction.selection_id,
            fragment_id=fragment_id,
        )
        selection = app_spec.selection(selection_ref)
        if selection is None:
            raise ValueError(
                f"Click {fragment_id}:{interaction.id} references unknown "
                f"selection {interaction.selection_id!r}"
            )
        selection_target_ref = app_ref(
            selection.target_id,
            fragment_id=selection_ref.fragment_id,
        )
        expected_target_ref = (
            scope_ref
            if selection.target_type == "geometry"
            else target_ref
        )
        if expected_target_ref is None:
            raise ValueError(
                f"Click {fragment_id}:{interaction.id} cannot link geometry "
                f"selection {interaction.selection_id!r} without a result scope"
            )
        if selection_target_ref != expected_target_ref:
            raise ValueError(
                f"Click {fragment_id}:{interaction.id} result scope does not match "
                f"linked selection "
                f"{interaction.selection_id!r} target {selection.target_id!r}"
            )
        if selection.item_kind != interaction.result_kind:
            raise ValueError(
                f"Click {fragment_id}:{interaction.id} result kind "
                f"{interaction.result_kind!r} does not match linked selection "
                f"{interaction.selection_id!r} item kind {selection.item_kind!r}"
            )

    for pointer in fragment.interactions.pointer_interactions.values():
        target_ref = app_ref(
            pointer.hit_target_id,
            fragment_id=fragment_id,
        )
        if app_spec.hit_target(target_ref) is None:
            raise ValueError(
                f"Pointer interaction {fragment_id}:{pointer.id} references unknown "
                f"hit target {pointer.hit_target_id!r}"
            )
        geometry_ref = (
            None
            if pointer.geometry_scope_id is None
            else app_ref(pointer.geometry_scope_id, fragment_id=fragment_id)
        )
        if geometry_ref is not None and app_spec.geometry(geometry_ref) is None:
            raise ValueError(
                f"Pointer interaction {fragment_id}:{pointer.id} references "
                f"unknown result scope geometry {pointer.geometry_scope_id!r}"
            )
        if geometry_ref is not None:
            for view in fragment.view_catalog.views.values():
                target_roles = tuple(
                    role
                    for role, target_id in view.hit_targets.items()
                    if app_ref(target_id, fragment_id=fragment_id) == target_ref
                )
                if not target_roles:
                    continue
                declared_geometry_refs = {
                    app_ref(geometry_id, fragment_id=fragment_id)
                    for geometry_id in view.geometries.values()
                }
                if geometry_ref not in declared_geometry_refs:
                    raise ValueError(
                        f"View {fragment_id}:{view.id} exposes pointer target "
                        f"{pointer.hit_target_id!r} for roles {target_roles!r} "
                        f"without result scope geometry "
                        f"{pointer.geometry_scope_id!r}"
                    )

    for contribution in fragment.view_catalog.contributions.values():
        for role, source_id in contribution.inputs.items():
            source_ref = app_ref(source_id, fragment_id=fragment_id)
            if (
                app_spec.field_spec(source_ref) is None
                and app_spec.operator(source_ref) is None
            ):
                raise ValueError(
                    f"Visual contribution {fragment_id}:{contribution.id} input "
                    f"{role!r} references unknown data source {source_id!r}"
                )
        for role, geometry_id in contribution.geometries.items():
            geometry_ref = app_ref(geometry_id, fragment_id=fragment_id)
            if app_spec.geometry(geometry_ref) is None:
                raise ValueError(
                    f"Visual contribution {fragment_id}:{contribution.id} geometry "
                    f"{role!r} references unknown geometry {geometry_id!r}"
                )
        for role, target_id in contribution.hit_targets.items():
            target_ref = app_ref(target_id, fragment_id=fragment_id)
            target = app_spec.hit_target(target_ref)
            if target is None:
                raise ValueError(
                    f"Visual contribution {fragment_id}:{contribution.id} hit target "
                    f"{role!r} references unknown target {target_id!r}"
                )
        for role, selection_id in contribution.selections.items():
            selection_ref = app_ref(selection_id, fragment_id=fragment_id)
            selection = app_spec.selection(selection_ref)
            if selection is None:
                raise ValueError(
                    f"Visual contribution {fragment_id}:{contribution.id} selection "
                    f"{role!r} references unknown selection {selection_id!r}"
                )
            selection_target_ref = app_ref(
                selection.target_id,
                fragment_id=selection_ref.fragment_id,
            )
            declared_targets = (
                {
                    app_ref(geometry_id, fragment_id=fragment_id)
                    for geometry_id in contribution.geometries.values()
                }
                if selection.target_type == "geometry"
                else {
                    app_ref(target_id, fragment_id=fragment_id)
                    for target_id in contribution.hit_targets.values()
                }
            )
            if selection_target_ref not in declared_targets:
                raise ValueError(
                    f"Visual contribution {fragment_id}:{contribution.id} selection "
                    f"{role!r} belongs to {selection.target_type} "
                    f"{selection.target_id!r}, "
                    "which the contribution does not declare"
                )

    for operator in fragment.view_catalog.operators.values():
        for role, source_id in operator.inputs.items():
            source_ref = app_ref(source_id, fragment_id=fragment_id)
            if (
                app_spec.field_spec(source_ref) is None
                and app_spec.operator(source_ref) is None
            ):
                raise ValueError(
                    f"Operator {source_ref.fragment_id}:{operator.id} input "
                    f"{role!r} references unknown data source {source_id!r}"
                )
        for role, geometry_id in operator.geometries.items():
            geometry_ref = app_ref(geometry_id, fragment_id=fragment_id)
            if app_spec.geometry(geometry_ref) is None:
                raise ValueError(
                    f"Operator {fragment_id}:{operator.id} geometry "
                    f"{role!r} references unknown geometry {geometry_id!r}"
                )

    _validate_operator_cycles(app_spec, fragment_id, fragment)


def _validate_operator_cycles(
    app_spec: AppSpec,
    fragment_id: str,
    fragment: AppFragmentSpec,
) -> None:
    """Reject recursive operator graphs before a frontend attempts resolution."""

    state: dict[AppRef, int] = {}
    path: list[AppRef] = []

    def visit(operator_ref: AppRef) -> None:
        marker = state.get(operator_ref, 0)
        if marker == 2:
            return
        if marker == 1:
            start = path.index(operator_ref)
            cycle = (*path[start:], operator_ref)
            rendered = " -> ".join(str(ref) for ref in cycle)
            raise ValueError(f"Operator dependency cycle: {rendered}")

        operator = app_spec.operator(operator_ref)
        if operator is None:
            return
        state[operator_ref] = 1
        path.append(operator_ref)
        for source_id in operator.inputs.values():
            source_ref = app_ref(
                source_id,
                fragment_id=operator_ref.fragment_id,
            )
            if app_spec.operator(source_ref) is not None:
                visit(source_ref)
        path.pop()
        state[operator_ref] = 2

    for operator_id in fragment.view_catalog.operators:
        visit(app_ref(operator_id, fragment_id=fragment_id))


def _validate_layout(
    app_spec: AppSpec,
    layout_id: str,
    layout: LayoutSpec,
    *,
    fragment_id: str | None = None,
) -> None:
    panel_by_id: dict[str, PanelSpec] = {}
    used_views: set[AppRef] = set()

    for panel in layout.panels:
        if fragment_id is not None:
            validate_local_id(
                panel.id,
                path=f"Layout {layout_id!r} local panel id",
            )
        panel_id = panel.id.strip()
        if not panel_id:
            raise ValueError(f"Layout {layout_id!r} contains a panel with an empty id")
        if panel_id in panel_by_id:
            raise ValueError(
                f"Layout {layout_id!r} contains duplicate panel id {panel_id!r}"
            )
        panel_by_id[panel_id] = panel
        _validate_panel(app_spec, layout_id, panel, used_views, fragment_id=fragment_id)

    if layout.panels and not layout.panel_grid:
        raise ValueError(
            f"Layout {layout_id!r} declares panels but no panel_grid. "
            "Build an explicit grid before constructing AppSpec."
        )

    grid_panel_ids: set[str] = set()
    for row in layout.panel_grid:
        if not row:
            raise ValueError(f"Layout {layout_id!r} contains an empty panel_grid row")
        for panel_id in row:
            if panel_id not in panel_by_id:
                raise ValueError(
                    f"Layout {layout_id!r} panel_grid references unknown panel {panel_id!r}"
                )
            if panel_id in grid_panel_ids:
                raise ValueError(
                    f"Layout {layout_id!r} panel_grid references panel {panel_id!r} more than once"
                )
            grid_panel_ids.add(panel_id)

    missing_from_grid = set(panel_by_id) - grid_panel_ids
    if missing_from_grid:
        joined = ", ".join(sorted(missing_from_grid))
        raise ValueError(f"Layout {layout_id!r} panel_grid omits panels: {joined}")


def _validate_panel(
    app_spec: AppSpec,
    layout_id: str,
    panel: PanelSpec,
    used_views: set[AppRef],
    *,
    fragment_id: str | None = None,
) -> None:
    if panel.control_ids:
        for control_id in panel.control_ids:
            if app_spec.control(_scoped_ref(control_id, fragment_id)) is None:
                raise ValueError(
                    f"Layout {layout_id!r} panel {panel.id!r} references unknown control {_format_ref(control_id)!r}"
                )
    if panel.view_ids:
        # Every view-bearing panel -- built-in or third-party -- is validated the
        # same way: each referenced view must exist and must DECLARE this panel's
        # kind (``view.panel_kind``). No isinstance, no per-kind branch, no list of
        # blessed view types, and no rejection of unknown panel kinds -- so a
        # third-party view/panel kind is a first-class citizen the core needs zero
        # knowledge of. Arity and renderer compatibility are the frontend's concern.
        for view_id in panel.view_ids:
            view = app_spec.view(_scoped_ref(view_id, fragment_id))
            if view is None:
                raise ValueError(
                    f"Layout {layout_id!r} panel {panel.id!r} references unknown view {_format_ref(view_id)!r}"
                )
            if view.panel_kind != panel.kind:
                raise ValueError(
                    f"Layout {layout_id!r} panel {panel.id!r} (kind {panel.kind!r}) references view "
                    f"{_format_ref(view_id)!r} declared for panel kind {view.panel_kind!r}"
                )
        _validate_panel_view_uniqueness(
            layout_id, panel, used_views, fragment_id=fragment_id
        )

    for contribution_id in panel.contribution_ids:
        if (
            app_spec.visual_contribution(
                _scoped_ref(contribution_id, fragment_id)
            )
            is None
        ):
            raise ValueError(
                f"Layout {layout_id!r} panel {panel.id!r} references unknown "
                f"visual contribution {_format_ref(contribution_id)!r}"
            )


def _validate_panel_view_uniqueness(
    layout_id: str,
    panel: PanelSpec,
    used_views: set[AppRef],
    *,
    fragment_id: str | None = None,
) -> None:
    view_refs = tuple(_scoped_ref(view_id, fragment_id) for view_id in panel.view_ids)
    repeated = sorted(str(view_ref) for view_ref in view_refs if view_ref in used_views)
    if repeated:
        raise ValueError(
            f"Layout {layout_id!r} assigns views to multiple panels: {', '.join(repeated)}"
        )
    used_views.update(view_refs)


def _format_ref(value: str | AppRef) -> str:
    return str(app_ref(value))


def _scoped_ref(value: str | AppRef, fragment_id: str | None) -> AppRef:
    if fragment_id is None:
        return app_ref(value)
    return app_ref(value, fragment_id=fragment_id)
