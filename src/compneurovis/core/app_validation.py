from __future__ import annotations

from compneurovis.core.app_spec import (
    AppFragmentSpec,
    AppSpec,
    LayoutSpec,
    PanelSpec,
)
from compneurovis.core.operators import ExtensionOperatorSpec
from compneurovis.core.references import AppRef, app_ref
from compneurovis.core.views import ExtensionViewSpec

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
        if not isinstance(view, ExtensionViewSpec):
            continue
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
            selection_geometry_ref = app_ref(
                selection.geometry_id,
                fragment_id=selection_ref.fragment_id,
            )
            view_geometry_refs = {
                app_ref(geometry_id, fragment_id=fragment_id)
                for geometry_id in view.geometries.values()
            }
            if selection_geometry_ref not in view_geometry_refs:
                raise ValueError(
                    f"View {selection_ref.fragment_id}:{view.id} selection "
                    f"{role!r} belongs to geometry {selection.geometry_id!r}, "
                    "which the view does not declare"
                )

    for selection in fragment.interactions.selections.values():
        geometry_ref = app_ref(selection.geometry_id, fragment_id=fragment_id)
        if app_spec.geometry(geometry_ref) is None:
            raise ValueError(
                f"Selection {fragment_id}:{selection.id} references unknown "
                f"geometry {selection.geometry_id!r}"
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
        for role, selection_id in contribution.selections.items():
            selection_ref = app_ref(selection_id, fragment_id=fragment_id)
            if app_spec.selection(selection_ref) is None:
                raise ValueError(
                    f"Visual contribution {fragment_id}:{contribution.id} selection "
                    f"{role!r} references unknown selection {selection_id!r}"
                )

    for operator in fragment.view_catalog.operators.values():
        if not isinstance(operator, ExtensionOperatorSpec):
            continue
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
    if panel.control_ids or panel.action_ids:
        for control_id in panel.control_ids:
            if app_spec.control(_scoped_ref(control_id, fragment_id)) is None:
                raise ValueError(
                    f"Layout {layout_id!r} panel {panel.id!r} references unknown control {_format_ref(control_id)!r}"
                )
        for action_id in panel.action_ids:
            if app_spec.action(_scoped_ref(action_id, fragment_id)) is None:
                raise ValueError(
                    f"Layout {layout_id!r} panel {panel.id!r} references unknown action {_format_ref(action_id)!r}"
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
