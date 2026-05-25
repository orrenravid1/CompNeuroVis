from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from compneurovis.core.controls import ActionSpec, ControlSpec
from compneurovis.core.field import FieldSpec
from compneurovis.core.geometry import GeometrySpec
from compneurovis.core.operators import OperatorSpec
from compneurovis.core.views import (
    LinePlotViewSpec,
    MorphologyViewSpec,
    StateGraphViewSpec,
    SurfaceViewSpec,
    ViewSpec,
)


PANEL_KIND_VIEW_3D = "view_3d"
PANEL_KIND_LINE_PLOT = "line_plot"
PANEL_KIND_CONTROLS = "controls"
PANEL_KIND_STATE_GRAPH = "state_graph"


@dataclass(slots=True)
class PanelSpec:
    id: str
    kind: str
    view_ids: tuple[str, ...] = ()
    control_ids: tuple[str, ...] = ()
    action_ids: tuple[str, ...] = ()
    operator_ids: tuple[str, ...] = ()
    host_kind: str = "independent_canvas"
    title: str | None = None
    camera_distance: float | None = 200.0
    camera_elevation: float = 30.0
    camera_azimuth: float = 30.0

    def __post_init__(self) -> None:
        self.view_ids = tuple(self.view_ids)
        self.control_ids = tuple(self.control_ids)
        self.action_ids = tuple(self.action_ids)
        self.operator_ids = tuple(self.operator_ids)


@dataclass(slots=True)
class LayoutSpec:
    title: str = "CompNeuroVis"
    panels: tuple[PanelSpec, ...] = ()
    panel_grid: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        self.panels = tuple(self.panels)
        self.panel_grid = tuple(tuple(row) for row in self.panel_grid)

    def panels_of_kind(self, kind: str) -> tuple[PanelSpec, ...]:
        return tuple(panel for panel in self.panels if panel.kind == kind)

    def panel(self, panel_id: str) -> PanelSpec | None:
        for panel in self.panels:
            if panel.id == panel_id:
                return panel
        return None

    def panel_for_view(self, view_id: str, *, kind: str | None = None) -> PanelSpec | None:
        for panel in self.panels:
            if kind is not None and panel.kind != kind:
                continue
            if view_id in panel.view_ids:
                return panel
        return None


@dataclass(slots=True)
class DataCatalog:
    fields: dict[str, FieldSpec] = field(default_factory=dict)
    geometries: dict[str, GeometrySpec] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.fields = dict(self.fields)
        self.geometries = dict(self.geometries)


@dataclass(slots=True)
class ViewCatalog:
    views: dict[str, ViewSpec] = field(default_factory=dict)
    operators: dict[str, OperatorSpec] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.views = dict(self.views)
        self.operators = dict(self.operators)


@dataclass(slots=True)
class InteractionCatalog:
    controls: dict[str, ControlSpec] = field(default_factory=dict)
    actions: dict[str, ActionSpec] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.controls = dict(self.controls)
        self.actions = dict(self.actions)


@dataclass(slots=True)
class LayoutCatalog:
    layouts: dict[str, LayoutSpec] = field(default_factory=lambda: {"default": LayoutSpec()})
    active: str = "default"

    def __post_init__(self) -> None:
        self.layouts = dict(self.layouts)
        if not self.layouts:
            self.layouts = {"default": LayoutSpec()}
            self.active = "default"
        if self.active not in self.layouts:
            raise ValueError(f"Active layout {self.active!r} is not present in LayoutCatalog.layouts")

    @classmethod
    def single(cls, layout: LayoutSpec | None = None) -> "LayoutCatalog":
        return cls(layouts={"default": layout or LayoutSpec()}, active="default")

    def active_layout(self) -> LayoutSpec:
        return self.layouts[self.active]


def build_default_layout(
    *,
    views: dict[str, ViewSpec],
    controls: dict[str, ControlSpec] | None = None,
    actions: dict[str, ActionSpec] | None = None,
    title: str = "CompNeuroVis",
) -> LayoutSpec:
    """Build the authoring-layer default layout before constructing AppSpec."""

    controls = {} if controls is None else dict(controls)
    actions = {} if actions is None else dict(actions)
    panels: list[PanelSpec] = []
    for view in views.values():
        if isinstance(view, (MorphologyViewSpec, SurfaceViewSpec)):
            panels.append(
                PanelSpec(
                    id=f"{view.id}-panel",
                    kind=PANEL_KIND_VIEW_3D,
                    view_ids=(view.id,),
                )
            )
        elif isinstance(view, LinePlotViewSpec):
            panels.append(
                PanelSpec(
                    id=f"{view.id}-panel",
                    kind=PANEL_KIND_LINE_PLOT,
                    view_ids=(view.id,),
                )
            )
        elif isinstance(view, StateGraphViewSpec):
            panels.append(
                PanelSpec(
                    id=f"{view.id}-panel",
                    kind=PANEL_KIND_STATE_GRAPH,
                    view_ids=(view.id,),
                )
            )

    if controls or actions:
        panels.append(
            PanelSpec(
                id="controls-panel",
                kind=PANEL_KIND_CONTROLS,
                control_ids=tuple(controls.keys()),
                action_ids=tuple(actions.keys()),
            )
        )

    return LayoutSpec(
        title=title,
        panels=tuple(panels),
        panel_grid=default_panel_grid(tuple(panels)),
    )


def build_default_layout_catalog(
    *,
    views: dict[str, ViewSpec],
    controls: dict[str, ControlSpec] | None = None,
    actions: dict[str, ActionSpec] | None = None,
    title: str = "CompNeuroVis",
) -> LayoutCatalog:
    return LayoutCatalog.single(
        build_default_layout(
            views=views,
            controls=controls,
            actions=actions,
            title=title,
        )
    )


def default_panel_grid(panels: tuple[PanelSpec, ...]) -> tuple[tuple[str, ...], ...]:
    non_controls = tuple(panel.id for panel in panels if panel.kind != PANEL_KIND_CONTROLS)
    controls = tuple(panel.id for panel in panels if panel.kind == PANEL_KIND_CONTROLS)
    rows: list[tuple[str, ...]] = []
    if non_controls:
        rows.append(non_controls)
    rows.extend((panel_id,) for panel_id in controls)
    return tuple(rows)


@dataclass(slots=True)
class AppSpec:
    data: DataCatalog = field(default_factory=DataCatalog)
    view_catalog: ViewCatalog = field(default_factory=ViewCatalog)
    interactions: InteractionCatalog = field(default_factory=InteractionCatalog)
    layout_catalog: LayoutCatalog = field(default_factory=LayoutCatalog)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.data = DataCatalog(fields=self.data.fields, geometries=self.data.geometries)
        self.view_catalog = ViewCatalog(
            views=self.view_catalog.views,
            operators=self.view_catalog.operators,
        )
        self.interactions = InteractionCatalog(
            controls=self.interactions.controls,
            actions=self.interactions.actions,
        )
        self.layout_catalog = LayoutCatalog(
            layouts=copy.deepcopy(self.layout_catalog.layouts),
            active=self.layout_catalog.active,
        )
        self.metadata = dict(self.metadata)
        validate_app_spec(self)


def validate_app_spec(app_spec: AppSpec) -> None:
    """Validate blueprint integrity without normalizing or mutating it."""
    for layout_id, layout in app_spec.layout_catalog.layouts.items():
        _validate_layout(app_spec, layout_id, layout)


def _validate_layout(app_spec: AppSpec, layout_id: str, layout: LayoutSpec) -> None:
    panel_by_id: dict[str, PanelSpec] = {}
    used_views: set[str] = set()

    for panel in layout.panels:
        panel_id = panel.id.strip()
        if not panel_id:
            raise ValueError(f"Layout {layout_id!r} contains a panel with an empty id")
        if panel_id in panel_by_id:
            raise ValueError(f"Layout {layout_id!r} contains duplicate panel id {panel_id!r}")
        panel_by_id[panel_id] = panel
        _validate_panel(app_spec, layout_id, panel, used_views)

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


def _validate_panel(app_spec: AppSpec, layout_id: str, panel: PanelSpec, used_views: set[str]) -> None:
    if panel.kind == PANEL_KIND_VIEW_3D:
        if not panel.view_ids:
            raise ValueError(f"Layout {layout_id!r} 3D panel {panel.id!r} must reference at least one view")
        for view_id in panel.view_ids:
            view = app_spec.view_catalog.views.get(view_id)
            if not isinstance(view, (MorphologyViewSpec, SurfaceViewSpec)):
                raise ValueError(
                    f"Layout {layout_id!r} 3D panel {panel.id!r} references non-3D view {view_id!r}"
                )
        _validate_panel_view_uniqueness(layout_id, panel, used_views)
    elif panel.kind == PANEL_KIND_LINE_PLOT:
        if len(panel.view_ids) != 1:
            raise ValueError(f"Layout {layout_id!r} line plot panel {panel.id!r} must reference exactly one view")
        view_id = panel.view_ids[0]
        if not isinstance(app_spec.view_catalog.views.get(view_id), LinePlotViewSpec):
            raise ValueError(
                f"Layout {layout_id!r} line plot panel {panel.id!r} references non-line-plot view {view_id!r}"
            )
        _validate_panel_view_uniqueness(layout_id, panel, used_views)
    elif panel.kind == PANEL_KIND_STATE_GRAPH:
        if len(panel.view_ids) != 1:
            raise ValueError(f"Layout {layout_id!r} state graph panel {panel.id!r} must reference exactly one view")
        view_id = panel.view_ids[0]
        if not isinstance(app_spec.view_catalog.views.get(view_id), StateGraphViewSpec):
            raise ValueError(
                f"Layout {layout_id!r} state graph panel {panel.id!r} references non-state-graph view {view_id!r}"
            )
        _validate_panel_view_uniqueness(layout_id, panel, used_views)
    elif panel.kind == PANEL_KIND_CONTROLS:
        for control_id in panel.control_ids:
            if control_id not in app_spec.interactions.controls:
                raise ValueError(
                    f"Layout {layout_id!r} controls panel {panel.id!r} references unknown control {control_id!r}"
                )
        for action_id in panel.action_ids:
            if action_id not in app_spec.interactions.actions:
                raise ValueError(
                    f"Layout {layout_id!r} controls panel {panel.id!r} references unknown action {action_id!r}"
                )
        if not panel.control_ids and not panel.action_ids:
            raise ValueError(
                f"Layout {layout_id!r} controls panel {panel.id!r} must reference at least one control or action"
            )
    else:
        raise ValueError(f"Layout {layout_id!r} contains unsupported panel kind {panel.kind!r}")

    for operator_id in panel.operator_ids:
        if operator_id not in app_spec.view_catalog.operators:
            raise ValueError(
                f"Layout {layout_id!r} panel {panel.id!r} references unknown operator {operator_id!r}"
            )


def _validate_panel_view_uniqueness(layout_id: str, panel: PanelSpec, used_views: set[str]) -> None:
    repeated = sorted(view_id for view_id in panel.view_ids if view_id in used_views)
    if repeated:
        raise ValueError(
            f"Layout {layout_id!r} assigns views to multiple panels: {', '.join(repeated)}"
        )
    used_views.update(panel.view_ids)


@dataclass(slots=True)
class ActorSpec:
    id: str
    host_source: Any = None  # ActorHostSource: Callable[[AppRuntime, Channel | None], Startable] | None
    runs_in_foreground: bool = False


@dataclass(slots=True)
class MessageMatch:
    """Generic message predicate used by RoutingSpec."""

    intent: Literal["command", "update"] | None = None
    message_type: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.attrs = dict(self.attrs)


@dataclass(slots=True)
class RouteSpec:
    """One ordered routing rule."""

    match: MessageMatch
    targets: tuple[str, ...]

    def __post_init__(self) -> None:
        self.targets = tuple(self.targets)


@dataclass(slots=True, init=False)
class RoutingSpec:
    """Ordered routing policy read by the Bus.

    Routing is generic: rules match message intent, registered message type
    name, and optional payload attributes. The Bus does not hardcode control,
    action, field, frame, or frontend concepts.
    """

    routes: tuple[RouteSpec, ...]
    default_targets: dict[Literal["command", "update"], tuple[str, ...]]

    def __init__(
        self,
        *,
        routes: tuple[RouteSpec, ...] | list[RouteSpec] = (),
        default_targets: dict[Literal["command", "update"], tuple[str, ...]] | None = None,
    ) -> None:
        self.routes = tuple(routes)
        self.default_targets = {
            intent: tuple(targets)
            for intent, targets in (default_targets or {}).items()
        }


@dataclass(slots=True)
class RunSpec:
    app_spec: AppSpec | None = None
    actors: list[ActorSpec] = field(default_factory=list)
    transport: Any | None = None  # TransportFactory: Callable[[list[ActorSpec], RoutingSpec | None], ...]
    routing: RoutingSpec | None = None
    diagnostics: DiagnosticsSpec | None = None


@dataclass(slots=True)
class DiagnosticsSpec:
    perf_log_enabled: bool = False
    perf_log_dir: str | Path | None = None
    perf_echo_stderr: bool = False
