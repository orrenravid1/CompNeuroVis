from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from compneurovis.core._immutability import FrozenDict
from compneurovis.core.controls import ActionSpec, ControlSpec
from compneurovis.core.field import FieldSpec
from compneurovis.core.geometry import GeometrySpec
from compneurovis.core.operators import OperatorSpec
from compneurovis.core.specs import IdentifiedSpec, SpecBase
from compneurovis.core.views import (
    BarPlotViewSpec,
    ExtensionViewSpec,
    LinePlotViewSpec,
    MorphologyViewSpec,
    StateGraphViewSpec,
    SurfaceViewSpec,
    ViewSpec,
)


PANEL_KIND_VIEW_3D = "view_3d"
PANEL_KIND_LINE_PLOT = "line_plot"
PANEL_KIND_BAR_PLOT = "bar_plot"
PANEL_KIND_CONTROLS = "controls"
PANEL_KIND_STATE_GRAPH = "state_graph"
PANEL_KIND_EXTENSION = "extension"
DEFAULT_FRAGMENT_ID = "main"


@dataclass(frozen=True, slots=True)
class AppRef(SpecBase):
    """Reference to an object inside one app fragment.

    ``id`` is the local id inside ``fragment_id``.
    """

    id: str
    fragment_id: str = DEFAULT_FRAGMENT_ID

    def __post_init__(self) -> None:
        fragment_id = str(self.fragment_id or DEFAULT_FRAGMENT_ID)
        local_id = str(self.id)
        if not fragment_id.strip():
            raise ValueError("AppRef.fragment_id cannot be empty")
        if not local_id.strip():
            raise ValueError("AppRef.id cannot be empty")
        if ":" in fragment_id or ":" in local_id:
            raise ValueError(
                "AppRef values cannot contain ':'. Construct scoped references as "
                "AppRef(id='field', fragment_id='source')."
            )
        object.__setattr__(self, "fragment_id", fragment_id)
        object.__setattr__(self, "id", local_id)

    def flat_id(self) -> str:
        if self.fragment_id == DEFAULT_FRAGMENT_ID:
            return self.id
        return f"{self.fragment_id}:{self.id}"

    def __str__(self) -> str:
        return self.flat_id()


def app_ref(value: str | AppRef, *, fragment_id: str = DEFAULT_FRAGMENT_ID) -> AppRef:
    """Resolve a string local id or existing AppRef to an AppRef.

    Existing refs already carry scope and are returned unchanged. To intentionally
    rescope a ref, construct ``AppRef(existing.id, fragment_id=...)`` explicitly.
    """

    if isinstance(value, AppRef):
        return value
    return AppRef(str(value), fragment_id=fragment_id)


@dataclass(frozen=True, slots=True)
class PanelSpec(IdentifiedSpec):
    kind: str
    view_ids: tuple[str | AppRef, ...] = ()
    control_ids: tuple[str | AppRef, ...] = ()
    action_ids: tuple[str | AppRef, ...] = ()
    operator_ids: tuple[str | AppRef, ...] = ()
    host_kind: str = "independent_canvas"
    title: str | None = None
    camera_distance: float | None = 200.0
    camera_elevation: float = 30.0
    camera_azimuth: float = 30.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "view_ids", tuple(self.view_ids))
        object.__setattr__(self, "control_ids", tuple(self.control_ids))
        object.__setattr__(self, "action_ids", tuple(self.action_ids))
        object.__setattr__(self, "operator_ids", tuple(self.operator_ids))


@dataclass(frozen=True, slots=True)
class LayoutSpec(SpecBase):
    title: str = "CompNeuroVis"
    panels: tuple[PanelSpec, ...] = ()
    panel_grid: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "panels", tuple(self.panels))
        object.__setattr__(self, "panel_grid", tuple(tuple(row) for row in self.panel_grid))

    def panels_of_kind(self, kind: str) -> tuple[PanelSpec, ...]:
        return tuple(panel for panel in self.panels if panel.kind == kind)

    def panel(self, panel_id: str) -> PanelSpec | None:
        for panel in self.panels:
            if panel.id == panel_id:
                return panel
        return None

    def panel_for_view(self, view_id: str | AppRef, *, kind: str | None = None) -> PanelSpec | None:
        for panel in self.panels:
            if kind is not None and panel.kind != kind:
                continue
            if view_id in panel.view_ids:
                return panel
        return None


@dataclass(frozen=True, slots=True)
class DataCatalog(SpecBase):
    fields: Mapping[str, FieldSpec] = field(default_factory=FrozenDict)
    geometries: Mapping[str, GeometrySpec] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", FrozenDict(self.fields))
        object.__setattr__(self, "geometries", FrozenDict(self.geometries))


@dataclass(frozen=True, slots=True)
class ViewCatalog(SpecBase):
    views: Mapping[str, ViewSpec] = field(default_factory=FrozenDict)
    operators: Mapping[str, OperatorSpec] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "views", FrozenDict(self.views))
        object.__setattr__(self, "operators", FrozenDict(self.operators))


@dataclass(frozen=True, slots=True)
class InteractionCatalog(SpecBase):
    controls: Mapping[str, ControlSpec] = field(default_factory=FrozenDict)
    actions: Mapping[str, ActionSpec] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "controls", FrozenDict(self.controls))
        object.__setattr__(self, "actions", FrozenDict(self.actions))


@dataclass(frozen=True, slots=True)
class LayoutCatalog(SpecBase):
    layouts: Mapping[str, LayoutSpec] = field(default_factory=lambda: FrozenDict({"default": LayoutSpec()}))
    active: str = "default"

    def __post_init__(self) -> None:
        layouts = dict(self.layouts)
        if not self.layouts:
            layouts = {"default": LayoutSpec()}
            object.__setattr__(self, "active", "default")
        object.__setattr__(self, "layouts", FrozenDict(layouts))
        if self.active not in self.layouts:
            raise ValueError(f"Active layout {self.active!r} is not present in LayoutCatalog.layouts")

    @classmethod
    def single(cls, layout: LayoutSpec | None = None) -> "LayoutCatalog":
        return cls(layouts={"default": layout or LayoutSpec()}, active="default")

    def active_layout(self) -> LayoutSpec:
        return self.layouts[self.active]


@dataclass(frozen=True, slots=True)
class AppFragmentSpec(IdentifiedSpec):
    """A source-local app fragment with local ids and local catalogs."""

    data: DataCatalog = field(default_factory=DataCatalog)
    view_catalog: ViewCatalog = field(default_factory=ViewCatalog)
    interactions: InteractionCatalog = field(default_factory=InteractionCatalog)
    layout_catalog: LayoutCatalog = field(default_factory=LayoutCatalog)
    metadata: Mapping[str, Any] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        fragment_id = str(self.id or DEFAULT_FRAGMENT_ID)
        if not fragment_id.strip():
            raise ValueError("AppFragmentSpec.id cannot be empty")
        object.__setattr__(self, "id", fragment_id)
        object.__setattr__(
            self,
            "data",
            DataCatalog(fields=self.data.fields, geometries=self.data.geometries),
        )
        object.__setattr__(
            self,
            "view_catalog",
            ViewCatalog(
                views=self.view_catalog.views,
                operators=self.view_catalog.operators,
            ),
        )
        object.__setattr__(
            self,
            "interactions",
            InteractionCatalog(
                controls=self.interactions.controls,
                actions=self.interactions.actions,
            ),
        )
        object.__setattr__(
            self,
            "layout_catalog",
            LayoutCatalog(
                layouts=self.layout_catalog.layouts,
                active=self.layout_catalog.active,
            ),
        )
        object.__setattr__(self, "metadata", FrozenDict(self.metadata))

    @classmethod
    def from_app_spec(cls, fragment_id: str, app_spec: "AppSpec") -> "AppFragmentSpec":
        return cls(
            id=fragment_id,
            data=app_spec.data,
            view_catalog=app_spec.view_catalog,
            interactions=app_spec.interactions,
            layout_catalog=app_spec.layout_catalog,
            metadata=app_spec.metadata,
        )

    def active_layout(self) -> LayoutSpec:
        return self.layout_catalog.active_layout()

    def ref(self, local_id: str) -> AppRef:
        return AppRef(id=local_id, fragment_id=self.id)


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
        elif isinstance(view, BarPlotViewSpec):
            panels.append(
                PanelSpec(
                    id=f"{view.id}-panel",
                    kind=PANEL_KIND_BAR_PLOT,
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
        elif isinstance(view, ExtensionViewSpec):
            panels.append(
                PanelSpec(
                    id=f"{view.id}-panel",
                    kind=PANEL_KIND_EXTENSION,
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


@dataclass(frozen=True, slots=True)
class AppSpec(SpecBase):
    data: DataCatalog = field(default_factory=DataCatalog)
    view_catalog: ViewCatalog = field(default_factory=ViewCatalog)
    interactions: InteractionCatalog = field(default_factory=InteractionCatalog)
    layout_catalog: LayoutCatalog = field(default_factory=LayoutCatalog)
    metadata: Mapping[str, Any] = field(default_factory=FrozenDict)
    fragments: Mapping[str, AppFragmentSpec] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        data = DataCatalog(fields=self.data.fields, geometries=self.data.geometries)
        view_catalog = ViewCatalog(
            views=self.view_catalog.views,
            operators=self.view_catalog.operators,
        )
        interactions = InteractionCatalog(
            controls=self.interactions.controls,
            actions=self.interactions.actions,
        )
        layout_catalog = LayoutCatalog(
            layouts=self.layout_catalog.layouts,
            active=self.layout_catalog.active,
        )
        metadata = FrozenDict(self.metadata)

        object.__setattr__(self, "data", data)
        object.__setattr__(self, "view_catalog", view_catalog)
        object.__setattr__(self, "interactions", interactions)
        object.__setattr__(self, "layout_catalog", layout_catalog)
        object.__setattr__(self, "metadata", metadata)

        fragments = dict(self.fragments)
        if not fragments:
            fragments = {
                DEFAULT_FRAGMENT_ID: AppFragmentSpec(
                    id=DEFAULT_FRAGMENT_ID,
                    data=data,
                    view_catalog=view_catalog,
                    interactions=interactions,
                    layout_catalog=layout_catalog,
                    metadata=metadata,
                )
            }
        else:
            fragments = {
                fragment_id: AppFragmentSpec(
                    id=fragment.id,
                    data=fragment.data,
                    view_catalog=fragment.view_catalog,
                    interactions=fragment.interactions,
                    layout_catalog=fragment.layout_catalog,
                    metadata=fragment.metadata,
                )
                for fragment_id, fragment in fragments.items()
            }
            for key, fragment in fragments.items():
                if key != fragment.id:
                    raise ValueError(
                        f"AppSpec.fragments key {key!r} must match AppFragmentSpec.id {fragment.id!r}"
                    )
        object.__setattr__(self, "fragments", FrozenDict(fragments))
        validate_app_spec(self)

    def fragment(self, fragment_id: str = DEFAULT_FRAGMENT_ID) -> AppFragmentSpec:
        return self.fragments[fragment_id]

    def ref(self, value: str | AppRef, *, fragment_id: str = DEFAULT_FRAGMENT_ID) -> AppRef:
        return app_ref(value, fragment_id=fragment_id)

    def field_spec(self, ref: str | AppRef) -> FieldSpec | None:
        resolved = app_ref(ref)
        return self.fragment(resolved.fragment_id).data.fields.get(resolved.id)

    def geometry(self, ref: str | AppRef) -> GeometrySpec | None:
        resolved = app_ref(ref)
        return self.fragment(resolved.fragment_id).data.geometries.get(resolved.id)

    def view(self, ref: str | AppRef) -> ViewSpec | None:
        resolved = app_ref(ref)
        return self.fragment(resolved.fragment_id).view_catalog.views.get(resolved.id)

    def operator(self, ref: str | AppRef) -> OperatorSpec | None:
        resolved = app_ref(ref)
        return self.fragment(resolved.fragment_id).view_catalog.operators.get(resolved.id)

    def control(self, ref: str | AppRef) -> ControlSpec | None:
        resolved = app_ref(ref)
        return self.fragment(resolved.fragment_id).interactions.controls.get(resolved.id)

    def action(self, ref: str | AppRef) -> ActionSpec | None:
        resolved = app_ref(ref)
        return self.fragment(resolved.fragment_id).interactions.actions.get(resolved.id)

    def iter_field_specs(self):
        for fragment in self.fragments.values():
            for local_id, field_spec in fragment.data.fields.items():
                yield AppRef(local_id, fragment.id), field_spec

    def iter_geometry_specs(self):
        for fragment in self.fragments.values():
            for local_id, geometry in fragment.data.geometries.items():
                yield AppRef(local_id, fragment.id), geometry

    def iter_view_specs(self):
        for fragment in self.fragments.values():
            for local_id, view in fragment.view_catalog.views.items():
                yield AppRef(local_id, fragment.id), view

    def iter_operator_specs(self):
        for fragment in self.fragments.values():
            for local_id, operator in fragment.view_catalog.operators.items():
                yield AppRef(local_id, fragment.id), operator

    def iter_controls(self):
        for fragment in self.fragments.values():
            for local_id, control in fragment.interactions.controls.items():
                yield AppRef(local_id, fragment.id), control

    def iter_actions(self):
        for fragment in self.fragments.values():
            for local_id, action in fragment.interactions.actions.items():
                yield AppRef(local_id, fragment.id), action


def validate_app_spec(app_spec: AppSpec) -> None:
    """Validate blueprint integrity without normalizing or mutating it."""
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
            raise ValueError(f"Layout {layout_id!r} contains duplicate panel id {panel_id!r}")
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
    if panel.kind == PANEL_KIND_VIEW_3D:
        if not panel.view_ids:
            raise ValueError(f"Layout {layout_id!r} 3D panel {panel.id!r} must reference at least one view")
        for view_id in panel.view_ids:
            view = app_spec.view(_scoped_ref(view_id, fragment_id))
            if not isinstance(view, (MorphologyViewSpec, SurfaceViewSpec)):
                raise ValueError(
                    f"Layout {layout_id!r} 3D panel {panel.id!r} references non-3D view {_format_ref(view_id)!r}"
                )
        _validate_panel_view_uniqueness(layout_id, panel, used_views, fragment_id=fragment_id)
    elif panel.kind == PANEL_KIND_LINE_PLOT:
        if len(panel.view_ids) != 1:
            raise ValueError(f"Layout {layout_id!r} line plot panel {panel.id!r} must reference exactly one view")
        view_id = panel.view_ids[0]
        if not isinstance(app_spec.view(_scoped_ref(view_id, fragment_id)), LinePlotViewSpec):
            raise ValueError(
                f"Layout {layout_id!r} line plot panel {panel.id!r} references non-line-plot view {_format_ref(view_id)!r}"
            )
        _validate_panel_view_uniqueness(layout_id, panel, used_views, fragment_id=fragment_id)
    elif panel.kind == PANEL_KIND_BAR_PLOT:
        if len(panel.view_ids) != 1:
            raise ValueError(f"Layout {layout_id!r} bar plot panel {panel.id!r} must reference exactly one view")
        view_id = panel.view_ids[0]
        if not isinstance(app_spec.view(_scoped_ref(view_id, fragment_id)), BarPlotViewSpec):
            raise ValueError(
                f"Layout {layout_id!r} bar plot panel {panel.id!r} references non-bar-plot view {_format_ref(view_id)!r}"
            )
        _validate_panel_view_uniqueness(layout_id, panel, used_views, fragment_id=fragment_id)
    elif panel.kind == PANEL_KIND_STATE_GRAPH:
        if len(panel.view_ids) != 1:
            raise ValueError(f"Layout {layout_id!r} state graph panel {panel.id!r} must reference exactly one view")
        view_id = panel.view_ids[0]
        if not isinstance(app_spec.view(_scoped_ref(view_id, fragment_id)), StateGraphViewSpec):
            raise ValueError(
                f"Layout {layout_id!r} state graph panel {panel.id!r} references non-state-graph view {_format_ref(view_id)!r}"
            )
        _validate_panel_view_uniqueness(layout_id, panel, used_views, fragment_id=fragment_id)
    elif panel.kind == PANEL_KIND_EXTENSION:
        if len(panel.view_ids) != 1:
            raise ValueError(
                f"Layout {layout_id!r} extension panel {panel.id!r} must reference exactly one view"
            )
        view_id = panel.view_ids[0]
        if not isinstance(app_spec.view(_scoped_ref(view_id, fragment_id)), ExtensionViewSpec):
            raise ValueError(
                f"Layout {layout_id!r} extension panel {panel.id!r} references "
                f"a non-extension view {_format_ref(view_id)!r}"
            )
        _validate_panel_view_uniqueness(layout_id, panel, used_views, fragment_id=fragment_id)
    elif panel.kind == PANEL_KIND_CONTROLS:
        for control_id in panel.control_ids:
            if app_spec.control(_scoped_ref(control_id, fragment_id)) is None:
                raise ValueError(
                    f"Layout {layout_id!r} controls panel {panel.id!r} references unknown control {_format_ref(control_id)!r}"
                )
        for action_id in panel.action_ids:
            if app_spec.action(_scoped_ref(action_id, fragment_id)) is None:
                raise ValueError(
                    f"Layout {layout_id!r} controls panel {panel.id!r} references unknown action {_format_ref(action_id)!r}"
                )
        if not panel.control_ids and not panel.action_ids:
            raise ValueError(
                f"Layout {layout_id!r} controls panel {panel.id!r} must reference at least one control or action"
            )
    else:
        raise ValueError(f"Layout {layout_id!r} contains unsupported panel kind {panel.kind!r}")

    for operator_id in panel.operator_ids:
        if app_spec.operator(_scoped_ref(operator_id, fragment_id)) is None:
            raise ValueError(
                f"Layout {layout_id!r} panel {panel.id!r} references unknown operator {_format_ref(operator_id)!r}"
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
