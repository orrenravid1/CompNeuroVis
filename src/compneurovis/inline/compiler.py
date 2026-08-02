"""Compile source-level widget bindings into a canonical AppSpec."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping, Protocol, Sequence, TypeAlias, runtime_checkable

from compneurovis.core.app_spec import (
    PANEL_KIND_CONTROLS,
    AppSpec,
    DataCatalog,
    InteractionCatalog,
    LayoutCatalog,
    LayoutSpec,
    PanelSpec,
    ViewCatalog,
)
from compneurovis.core.controls import ControlSpec
from compneurovis.core.field import FieldSpec
from compneurovis.core.geometry import GeometrySpec
from compneurovis.core.operators import OperatorSpec
from compneurovis.core.views import ViewSpec
from compneurovis.inline.interactions import ActionInteraction, ControlInteraction


FieldInput: TypeAlias = FieldSpec | Callable[[Any], FieldSpec]
GeometryInput: TypeAlias = GeometrySpec | Callable[[Any], GeometrySpec]
ViewInput: TypeAlias = ViewSpec | Callable[[Any], ViewSpec]


@dataclass(frozen=True, slots=True)
class WidgetContribution:
    """Internal compilation unit emitted by one source-level widget."""

    fields: tuple[FieldSpec, ...] = ()
    geometries: tuple[GeometrySpec, ...] = ()
    views: tuple[ViewSpec, ...] = ()
    operators: tuple[OperatorSpec, ...] = ()
    controls: tuple[ControlSpec, ...] = ()
    panel: PanelSpec | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", tuple(self.fields))
        object.__setattr__(self, "geometries", tuple(self.geometries))
        object.__setattr__(self, "views", tuple(self.views))
        object.__setattr__(self, "operators", tuple(self.operators))
        object.__setattr__(self, "controls", tuple(self.controls))


@runtime_checkable
class Binding(Protocol):
    """Internal source declaration that can emit a compilation unit."""

    def contribution(self, backend: Any = None) -> WidgetContribution:
        """Build canonical specs, optionally using a source backend."""


@dataclass
class SpecBinding:
    """Internal binding assembled from canonical specs or builders."""

    field_builders: tuple[FieldInput, ...] = ()
    geometries: tuple[GeometryInput, ...] = ()
    views: tuple[ViewInput, ...] = ()
    panel: PanelSpec | None = None
    controls: tuple[ControlSpec, ...] = ()

    def contribution(self, backend: Any = None) -> WidgetContribution:
        return WidgetContribution(
            fields=tuple(
                item(backend) if callable(item) else item
                for item in self.field_builders
            ),
            geometries=tuple(
                item(backend) if callable(item) else item for item in self.geometries
            ),
            views=tuple(
                item(backend) if callable(item) else item for item in self.views
            ),
            panel=self.panel,
            controls=self.controls,
        )


@dataclass(frozen=True, slots=True)
class StartupData:
    """Simulator-owned data available before source widgets are compiled."""

    fields: tuple[FieldSpec, ...] = ()
    geometries: tuple[GeometrySpec, ...] = ()
    title: str = "CompNeuroVis"
    metadata: Mapping[str, Any] | None = None

    def app_spec(self) -> AppSpec:
        return AppSpec(
            data=DataCatalog(
                fields={field.id: field for field in self.fields},
                geometries={geometry.id: geometry for geometry in self.geometries},
            ),
            view_catalog=ViewCatalog(),
            interactions=InteractionCatalog(),
            layout_catalog=LayoutCatalog.single(LayoutSpec(title=self.title)),
            metadata={} if self.metadata is None else dict(self.metadata),
        )


def _merge_specs(
    target: dict[str, Any],
    specs: Sequence[Any],
    expected_type: type[Any],
    catalog_name: str,
) -> None:
    for spec in specs:
        if not isinstance(spec, expected_type):
            raise TypeError(
                f"widget {catalog_name} contribution must contain "
                f"{expected_type.__name__} objects, got {type(spec).__name__}"
            )
        if spec.id in target:
            raise ValueError(f"duplicate {catalog_name} id {spec.id!r}")
        target[spec.id] = spec


def _widget_contribution(
    widget: Binding,
    backend: Any,
) -> WidgetContribution:
    if not isinstance(widget, Binding):
        raise TypeError(
            "widget binding must provide contribution(backend), "
            f"got {type(widget).__name__}"
        )
    contribution = widget.contribution(backend)
    if not isinstance(contribution, WidgetContribution):
        raise TypeError(
            f"{type(widget).__name__}.contribution() must return "
            f"WidgetContribution, got {type(contribution).__name__}"
        )
    return contribution


def append_bindings_to_app_spec(
    app_spec: AppSpec | StartupData,
    *,
    panel_bindings: Sequence[Binding] = (),
    controls: Sequence[ControlInteraction] = (),
    actions: Sequence[ActionInteraction] = (),
    backend: Any = None,
) -> AppSpec:
    """Merge source declarations into an immutable canonical AppSpec."""
    if isinstance(app_spec, StartupData):
        app_spec = app_spec.app_spec()

    fields = dict(app_spec.data.fields)
    geometries = dict(app_spec.data.geometries)
    views = dict(app_spec.view_catalog.views)
    operators = dict(app_spec.view_catalog.operators)
    controls_by_id = dict(app_spec.interactions.controls)
    actions_by_id = dict(app_spec.interactions.actions)
    layouts = dict(app_spec.layout_catalog.layouts)
    layout = layouts[app_spec.layout_catalog.active]
    panels = list(layout.panels)
    panel_grid = list(layout.panel_grid)
    panel_ids = {panel.id for panel in panels}
    extra_control_ids: list[str] = []

    for widget in panel_bindings:
        contribution = _widget_contribution(widget, backend)
        _merge_specs(fields, contribution.fields, FieldSpec, "field")
        _merge_specs(
            geometries,
            contribution.geometries,
            GeometrySpec,
            "geometry",
        )
        _merge_specs(views, contribution.views, ViewSpec, "view")
        _merge_specs(
            operators,
            contribution.operators,
            OperatorSpec,
            "operator",
        )
        _merge_specs(
            controls_by_id,
            contribution.controls,
            ControlSpec,
            "control",
        )
        for spec in contribution.controls:
            if spec.id not in extra_control_ids:
                extra_control_ids.append(spec.id)

        panel = contribution.panel
        if panel is None:
            continue
        if not isinstance(panel, PanelSpec):
            raise TypeError(
                "widget panel contribution must be PanelSpec, "
                f"got {type(panel).__name__}"
            )
        if panel.id in panel_ids:
            raise ValueError(f"duplicate panel id {panel.id!r}")
        panels.append(panel)
        panel_grid.append((panel.id,))
        panel_ids.add(panel.id)

    for control in controls:
        spec = control._control_spec()
        if spec.id in controls_by_id:
            raise ValueError(f"duplicate control id {spec.id!r}")
        controls_by_id[spec.id] = spec
    for action in actions:
        spec = action._action_spec()
        if spec.id in actions_by_id:
            raise ValueError(f"duplicate action id {spec.id!r}")
        actions_by_id[spec.id] = spec

    source_control_ids = tuple(control._control_id for control in controls)
    control_ids = tuple(dict.fromkeys((*extra_control_ids, *source_control_ids)))
    action_ids = tuple(action._action_id for action in actions if action.show_button)
    if control_ids or action_ids:
        controls_panel_index = next(
            (
                index
                for index, panel in enumerate(panels)
                if panel.kind == PANEL_KIND_CONTROLS
            ),
            None,
        )
        if controls_panel_index is None:
            controls_panel = PanelSpec(
                id="controls-panel",
                kind=PANEL_KIND_CONTROLS,
                control_ids=control_ids,
                action_ids=action_ids,
            )
            panels.append(controls_panel)
            panel_grid.append((controls_panel.id,))
        else:
            panel = panels[controls_panel_index]
            panels[controls_panel_index] = replace(
                panel,
                control_ids=tuple(dict.fromkeys((*panel.control_ids, *control_ids))),
                action_ids=tuple(dict.fromkeys((*panel.action_ids, *action_ids))),
            )

    layouts[app_spec.layout_catalog.active] = replace(
        layout,
        panels=tuple(panels),
        panel_grid=tuple(panel_grid),
    )
    return AppSpec(
        data=DataCatalog(fields=fields, geometries=geometries),
        view_catalog=ViewCatalog(views=views, operators=operators),
        interactions=InteractionCatalog(
            controls=controls_by_id,
            actions=actions_by_id,
        ),
        layout_catalog=LayoutCatalog(
            layouts=layouts,
            active=app_spec.layout_catalog.active,
        ),
        metadata=app_spec.metadata,
    )


__all__ = [
    "FieldInput",
    "GeometryInput",
    "SpecBinding",
    "StartupData",
    "ViewInput",
    "Binding",
    "WidgetContribution",
    "append_bindings_to_app_spec",
]
