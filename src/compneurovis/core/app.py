from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal, TypeAlias

from compneurovis.core.controls import ActionSpec, ControlSpec
from compneurovis.core.actor import ActorBase, ActorRole, ActorSource
from compneurovis.core.field import FieldSpec
from compneurovis.core.geometry import GeometrySpec
from compneurovis.core.operators import OperatorSpec
from compneurovis.core.views import LinePlotViewSpec, StateGraphViewSpec, MorphologyViewSpec, SurfaceViewSpec, ViewSpec


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


@dataclass(slots=True)
class LayoutSpec:
    title: str = "CompNeuroVis"
    panels: tuple[PanelSpec, ...] = ()
    panel_grid: tuple[tuple[str, ...], ...] = ()

    def resolved_panels(self) -> tuple[PanelSpec, ...]:
        return self.panels

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

    def patch_panel(self, panel_id: str, **changes) -> bool:
        """Apply ``dataclasses.replace`` changes to one panel in the panels tuple.

        Returns ``True`` if the panel was found and patched, ``False`` if not found.
        """
        for i, panel in enumerate(self.panels):
            if panel.id == panel_id:
                self.panels = (
                    *self.panels[:i],
                    replace(panel, **changes),
                    *self.panels[i + 1 :],
                )
                return True
        return False

    def replace_panels(
        self,
        panels: "tuple[PanelSpec, ...]",
        panel_grid: "tuple[tuple[str, ...], ...]" = (),
    ) -> None:
        """Replace the full panel inventory and optional grid. Does not re-normalize."""
        self.panels = panels
        self.panel_grid = panel_grid

    def normalize_panels(
        self,
        *,
        views: dict[str, ViewSpec],
        controls: dict[str, ControlSpec],
        actions: dict[str, ActionSpec],
    ) -> None:
        if self.panels:
            self.panels = self._normalize_explicit_panels(
                views=views,
                controls=controls,
                actions=actions,
            )
        else:
            self.panels = self._derive_default_panels(
                views=views,
                controls=controls,
                actions=actions,
            )

    def _normalize_explicit_panels(
        self,
        *,
        views: dict[str, ViewSpec],
        controls: dict[str, ControlSpec],
        actions: dict[str, ActionSpec],
    ) -> tuple[PanelSpec, ...]:
        normalized: list[PanelSpec] = []
        seen_panel_ids: set[str] = set()
        seen_view_ids: set[str] = set()

        for panel in self.panels:
            panel_id = panel.id.strip()
            if not panel_id:
                raise ValueError("PanelSpec.id must be non-empty")
            if panel_id in seen_panel_ids:
                raise ValueError(f"Duplicate panel id '{panel_id}'")

            if panel.kind == PANEL_KIND_VIEW_3D:
                view_ids = tuple(
                    dict.fromkeys(
                        view_id
                        for view_id in panel.view_ids
                        if view_id in views and isinstance(views[view_id], (MorphologyViewSpec, SurfaceViewSpec))
                    )
                )
                if not view_ids:
                    continue
                duplicate_view_ids = [view_id for view_id in view_ids if view_id in seen_view_ids]
                if duplicate_view_ids:
                    joined = ", ".join(duplicate_view_ids)
                    raise ValueError(f"3D view ids assigned to multiple panels: {joined}")
                seen_view_ids.update(view_ids)
                normalized.append(
                    PanelSpec(
                        id=panel_id,
                        kind=panel.kind,
                        view_ids=view_ids,
                        operator_ids=tuple(dict.fromkeys(operator_id for operator_id in panel.operator_ids if operator_id)),
                        host_kind=panel.host_kind,
                        title=panel.title,
                        camera_distance=panel.camera_distance,
                        camera_elevation=panel.camera_elevation,
                        camera_azimuth=panel.camera_azimuth,
                    )
                )
            elif panel.kind == PANEL_KIND_LINE_PLOT:
                view_ids = tuple(
                    dict.fromkeys(
                        view_id
                        for view_id in panel.view_ids
                        if view_id in views and isinstance(views[view_id], LinePlotViewSpec)
                    )
                )
                if not view_ids:
                    continue
                if len(view_ids) != 1:
                    raise ValueError(
                        f"Line plot panel '{panel_id}' must reference exactly one line-plot view id"
                    )
                duplicate_view_ids = [view_id for view_id in view_ids if view_id in seen_view_ids]
                if duplicate_view_ids:
                    joined = ", ".join(duplicate_view_ids)
                    raise ValueError(f"Line plot view ids assigned to multiple panels: {joined}")
                seen_view_ids.update(view_ids)
                normalized.append(
                    PanelSpec(
                        id=panel_id,
                        kind=panel.kind,
                        view_ids=view_ids,
                        title=panel.title,
                    )
                )
            elif panel.kind == PANEL_KIND_CONTROLS:
                control_ids = tuple(dict.fromkeys(control_id for control_id in panel.control_ids if control_id))
                action_ids = tuple(dict.fromkeys(action_id for action_id in panel.action_ids if action_id))
                if not control_ids and not action_ids:
                    control_ids = tuple(controls.keys())
                    action_ids = tuple(actions.keys())
                normalized.append(
                    PanelSpec(
                        id=panel_id,
                        kind=panel.kind,
                        control_ids=control_ids,
                        action_ids=action_ids,
                        title=panel.title,
                    )
                )
            elif panel.kind == PANEL_KIND_STATE_GRAPH:
                view_ids = tuple(
                    dict.fromkeys(
                        view_id
                        for view_id in panel.view_ids
                        if view_id in views and isinstance(views[view_id], StateGraphViewSpec)
                    )
                )
                if not view_ids:
                    continue
                if len(view_ids) != 1:
                    raise ValueError(
                        f"State graph panel '{panel_id}' must reference exactly one state-graph view id"
                    )
                duplicate_view_ids = [view_id for view_id in view_ids if view_id in seen_view_ids]
                if duplicate_view_ids:
                    raise ValueError(
                        f"State graph view ids assigned to multiple panels: {', '.join(duplicate_view_ids)}"
                    )
                seen_view_ids.update(view_ids)
                normalized.append(
                    PanelSpec(
                        id=panel_id,
                        kind=panel.kind,
                        view_ids=view_ids,
                        title=panel.title,
                    )
                )
            else:
                raise ValueError(f"Unsupported panel kind '{panel.kind}'")

            seen_panel_ids.add(panel_id)

        return tuple(normalized)

    def _derive_default_panels(
        self,
        *,
        views: dict[str, ViewSpec],
        controls: dict[str, ControlSpec],
        actions: dict[str, ActionSpec],
    ) -> tuple[PanelSpec, ...]:
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

        return tuple(panels)


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


@dataclass(slots=True, init=False)
class AppSpec:
    data: DataCatalog
    view_catalog: ViewCatalog
    interactions: InteractionCatalog
    layout_catalog: LayoutCatalog
    metadata: dict[str, Any]

    def __init__(
        self,
        *,
        data: DataCatalog | None = None,
        view_catalog: ViewCatalog | None = None,
        interactions: InteractionCatalog | None = None,
        layout_catalog: LayoutCatalog | None = None,
        metadata: dict[str, Any] | None = None,
        fields: dict[str, FieldSpec] | None = None,
        geometries: dict[str, GeometrySpec] | None = None,
        views: dict[str, ViewSpec] | None = None,
        controls: dict[str, ControlSpec] | None = None,
        actions: dict[str, ActionSpec] | None = None,
        layout: LayoutSpec | None = None,
    ) -> None:
        if data is not None and fields is not None:
            raise TypeError("Cannot pass both data=DataCatalog(...) and fields=... — use data=DataCatalog(...)")
        if view_catalog is not None and views is not None:
            raise TypeError("Cannot pass both view_catalog=ViewCatalog(...) and views=... — use view_catalog=ViewCatalog(...)")
        if interactions is not None and (controls is not None or actions is not None):
            raise TypeError("Cannot pass both interactions=InteractionCatalog(...) and controls/actions=... — use interactions=InteractionCatalog(...)")
        if layout_catalog is not None and layout is not None:
            raise TypeError("Cannot pass both layout_catalog=LayoutCatalog(...) and layout=... — use layout_catalog=LayoutCatalog(...)")

        resolved_data = data if data is not None else DataCatalog(
            fields=fields or {},
            geometries=geometries or {},
        )
        resolved_view_catalog = view_catalog if view_catalog is not None else ViewCatalog(views=views or {})
        resolved_interactions = interactions if interactions is not None else InteractionCatalog(
            controls=controls or {},
            actions=actions or {},
        )
        resolved_layout_catalog = layout_catalog if layout_catalog is not None else LayoutCatalog.single(layout)

        self.data = DataCatalog(fields=resolved_data.fields, geometries=resolved_data.geometries)
        self.view_catalog = ViewCatalog(views=resolved_view_catalog.views, operators=resolved_view_catalog.operators)
        self.interactions = InteractionCatalog(
            controls=resolved_interactions.controls,
            actions=resolved_interactions.actions,
        )
        self.layout_catalog = LayoutCatalog(
            layouts=resolved_layout_catalog.layouts,
            active=resolved_layout_catalog.active,
        )
        self.metadata = dict(metadata or {})
        self._normalize_layouts()

    def active_layout(self) -> LayoutSpec:
        return self.layout_catalog.active_layout()

    def _normalize_layouts(self) -> None:
        for layout in self.layout_catalog.layouts.values():
            layout.normalize_panels(
                views=self.view_catalog.views,
                controls=self.interactions.controls,
                actions=self.interactions.actions,
            )

    def replace_view(self, view_id: str, updates: dict[str, Any]) -> None:
        self.view_catalog.views[view_id] = replace(self.view_catalog.views[view_id], **updates)

    def replace_operator(self, operator_id: str, updates: dict[str, Any]) -> None:
        self.view_catalog.operators[operator_id] = replace(self.view_catalog.operators[operator_id], **updates)

    def replace_control(self, control_id: str, updates: dict[str, Any]) -> None:
        self.interactions.controls[control_id] = replace(self.interactions.controls[control_id], **updates)


@dataclass(slots=True)
class ActorSpec:
    id: str
    role: ActorRole
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
