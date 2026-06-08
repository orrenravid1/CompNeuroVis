from __future__ import annotations

import numpy as np

from compneurovis.core import (
    AppSpec,
    ControlSpec,
    DataCatalog,
    Field,
    GridSliceOperatorSpec,
    GridGeometrySpec,
    InteractionCatalog,
    LayoutCatalog,
    LayoutSpec,
    LinePlotViewSpec,
    OperatorSpec,
    PanelSpec,
    RunSpec,
    SurfaceViewSpec,
    ViewCatalog,
)
from compneurovis.core.app_spec import PANEL_KIND_CONTROLS, PANEL_KIND_LINE_PLOT, PANEL_KIND_VIEW_3D


def grid_field(
    *,
    field_id: str,
    values: np.ndarray,
    x_coords: np.ndarray,
    y_coords: np.ndarray,
    x_dim: str = "x",
    y_dim: str = "y",
    unit: str | None = None,
) -> tuple[Field, GridGeometrySpec]:
    """Create a Field/GridGeometrySpec pair from a 2-D array and coordinate vectors."""

    field = Field(
        id=field_id,
        values=np.asarray(values, dtype=np.float32),
        dims=(y_dim, x_dim),
        coords={
            y_dim: np.asarray(y_coords, dtype=np.float32),
            x_dim: np.asarray(x_coords, dtype=np.float32),
        },
        unit=unit,
    )
    geometry = GridGeometrySpec(
        id=f"{field_id}-grid",
        dims=(y_dim, x_dim),
        coords={
            y_dim: np.asarray(y_coords, dtype=np.float32),
            x_dim: np.asarray(x_coords, dtype=np.float32),
        },
    )
    return field, geometry


def build_surface_app(
    *,
    field: Field,
    geometry: GridGeometrySpec | None = None,
    title: str = "Surface",
    surface_view: SurfaceViewSpec | None = None,
    line_views: tuple[LinePlotViewSpec, ...] = (),
    operators: dict[str, OperatorSpec] | None = None,
    controls: dict[str, ControlSpec] | None = None,
    panels: tuple[PanelSpec, ...] = (),
    panel_grid: tuple[tuple[str, ...], ...] = (),
) -> RunSpec:
    """Build a static surface app from field data, optional geometry, and views."""

    if surface_view is None:
        surface_view = SurfaceViewSpec(
            id="surface",
            title=title,
            field_id=field.id,
            geometry_id=geometry.id if geometry is not None else None,
        )
    views = {surface_view.id: surface_view}
    layout = LayoutSpec(title=title)
    default_operator_ids = tuple(
        operator.id
        for operator in (operators or {}).values()
        if isinstance(operator, GridSliceOperatorSpec)
        and operator.field_id == field.id
        and (geometry is None or operator.geometry_id in {None, geometry.id})
    )
    resolved_line_views = tuple(view for view in line_views if view is not None)
    if resolved_line_views:
        for view in resolved_line_views:
            views[view.id] = view
    operators = {} if operators is None else dict(operators)
    controls = {} if controls is None else dict(controls)

    if panels:
        resolved_panels: list[PanelSpec] = []
        for panel in panels:
            if (
                panel.kind == PANEL_KIND_VIEW_3D
                and surface_view.id in panel.view_ids
                and not panel.operator_ids
                and default_operator_ids
            ):
                panel = PanelSpec(
                    id=panel.id,
                    kind=panel.kind,
                    view_ids=panel.view_ids,
                    control_ids=panel.control_ids,
                    action_ids=panel.action_ids,
                    operator_ids=default_operator_ids,
                    host_kind=panel.host_kind,
                    title=panel.title,
                    camera_distance=panel.camera_distance,
                    camera_elevation=panel.camera_elevation,
                    camera_azimuth=panel.camera_azimuth,
                )
            resolved_panels.append(panel)
        layout.panels = tuple(resolved_panels)
    else:
        derived_panels: list[PanelSpec] = [
            PanelSpec(
                id=f"{surface_view.id}-panel",
                kind=PANEL_KIND_VIEW_3D,
                view_ids=(surface_view.id,),
                operator_ids=default_operator_ids,
                camera_distance=30.0,
            )
        ]
        derived_panels.extend(
            PanelSpec(
                id=f"{view.id}-panel",
                kind=PANEL_KIND_LINE_PLOT,
                view_ids=(view.id,),
            )
            for view in resolved_line_views
        )
        if controls:
            derived_panels.append(
                PanelSpec(
                    id="controls-panel",
                    kind=PANEL_KIND_CONTROLS,
                    control_ids=tuple(controls.keys()),
                )
            )
        layout.panels = tuple(derived_panels)

    if panel_grid:
        layout.panel_grid = panel_grid
    else:
        non_controls = [panel.id for panel in layout.panels if panel.kind != PANEL_KIND_CONTROLS]
        controls_panels = [panel.id for panel in layout.panels if panel.kind == PANEL_KIND_CONTROLS]
        rows: list[tuple[str, ...]] = []
        if non_controls:
            rows.append(tuple(non_controls))
        rows.extend((panel_id,) for panel_id in controls_panels)
        layout.panel_grid = tuple(rows)

    app_spec = AppSpec(
        data=DataCatalog(
            fields={field.id: field},
            geometries={} if geometry is None else {geometry.id: geometry},
        ),
        view_catalog=ViewCatalog(views=views, operators=operators),
        interactions=InteractionCatalog(controls=controls),
        layout_catalog=LayoutCatalog.single(layout),
    )
    return RunSpec(app_spec=app_spec, title=title)
