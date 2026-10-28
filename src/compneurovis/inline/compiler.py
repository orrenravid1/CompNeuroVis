"""Compile source-level widget bindings into a canonical AppSpec."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping, Protocol, Sequence, TypeAlias, runtime_checkable

from compneurovis.core.app_spec import (
    AppSpec,
    DataCatalog,
    InteractionCatalog,
    LayoutCatalog,
    PanelSpec,
    ViewCatalog,
)
from compneurovis.core.controls import ControlSpec
from compneurovis.core._immutability import FrozenDict
from compneurovis.core.field import FieldRetentionSpec, FieldSpec
from compneurovis.core.clicks import ClickSpec
from compneurovis.core.pointer_interactions import PointerInteractionSpec
from compneurovis.core.pointer import HitTargetSpec
from compneurovis.core.geometry import GeometrySpec
from compneurovis.core.operators import OperatorSpec
from compneurovis.core.selections import SelectionSpec
from compneurovis.core.views import ViewSpec
from compneurovis.core.visual_contributions import VisualContributionSpec
from compneurovis.backends.startup import StartupData
from compneurovis.inline.interactions import (
    ControlInteraction,
    KeyBindingInteraction,
)


FieldInput: TypeAlias = FieldSpec | Callable[[Any], FieldSpec]
GeometryInput: TypeAlias = GeometrySpec | Callable[[Any], GeometrySpec]
ViewInput: TypeAlias = ViewSpec | Callable[[Any], ViewSpec]
SelectionInput: TypeAlias = SelectionSpec | Callable[[Any], SelectionSpec]
HitTargetInput: TypeAlias = HitTargetSpec | Callable[[Any], HitTargetSpec]
ClickInput: TypeAlias = ClickSpec | Callable[[Any], ClickSpec]
PointerInteractionInput: TypeAlias = PointerInteractionSpec | Callable[
    [Any], PointerInteractionSpec
]


@dataclass(frozen=True, slots=True)
class WidgetContribution:
    """Internal compilation unit emitted by one source-level widget."""

    fields: tuple[FieldSpec, ...] = ()
    field_retention: Mapping[str, tuple[FieldRetentionSpec, ...]] = field(
        default_factory=FrozenDict
    )
    geometries: tuple[GeometrySpec, ...] = ()
    views: tuple[ViewSpec, ...] = ()
    operators: tuple[OperatorSpec, ...] = ()
    visual_contributions: tuple[VisualContributionSpec, ...] = ()
    panel_contribution_ids: Mapping[str, tuple[str, ...]] = field(
        default_factory=FrozenDict
    )
    controls: tuple[ControlSpec, ...] = ()
    selections: tuple[SelectionSpec, ...] = ()
    hit_targets: tuple[HitTargetSpec, ...] = ()
    clicks: tuple[ClickSpec, ...] = ()
    pointer_interactions: tuple[PointerInteractionSpec, ...] = ()
    panel: PanelSpec | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", tuple(self.fields))
        object.__setattr__(
            self,
            "field_retention",
            FrozenDict(
                {
                    str(field_id): tuple(requirements)
                    for field_id, requirements in self.field_retention.items()
                }
            ),
        )
        object.__setattr__(self, "geometries", tuple(self.geometries))
        object.__setattr__(self, "views", tuple(self.views))
        object.__setattr__(self, "operators", tuple(self.operators))
        object.__setattr__(
            self, "visual_contributions", tuple(self.visual_contributions)
        )
        object.__setattr__(
            self,
            "panel_contribution_ids",
            FrozenDict(
                {
                    str(panel_id): tuple(contribution_ids)
                    for panel_id, contribution_ids in self.panel_contribution_ids.items()
                }
            ),
        )
        object.__setattr__(self, "controls", tuple(self.controls))
        object.__setattr__(self, "selections", tuple(self.selections))
        object.__setattr__(self, "hit_targets", tuple(self.hit_targets))
        object.__setattr__(self, "clicks", tuple(self.clicks))
        object.__setattr__(
            self,
            "pointer_interactions",
            tuple(self.pointer_interactions),
        )


@runtime_checkable
class Binding(Protocol):
    """Internal source declaration that can emit a compilation unit."""

    def contribution(self, backend: Any = None) -> WidgetContribution:
        """Build canonical specs, optionally using a source backend."""


@dataclass
class SpecBinding:
    """Internal binding assembled from canonical specs or builders."""

    field_builders: tuple[FieldInput, ...] = ()
    field_retention: Mapping[str, tuple[FieldRetentionSpec, ...]] = field(
        default_factory=FrozenDict
    )
    geometries: tuple[GeometryInput, ...] = ()
    views: tuple[ViewInput, ...] = ()
    operators: tuple[OperatorSpec, ...] = ()
    visual_contributions: tuple[VisualContributionSpec, ...] = ()
    panel_contribution_ids: Mapping[str, tuple[str, ...]] = field(
        default_factory=FrozenDict
    )
    panel: PanelSpec | None = None
    controls: tuple[ControlSpec, ...] = ()
    selections: tuple[SelectionInput, ...] = ()
    hit_targets: tuple[HitTargetInput, ...] = ()
    clicks: tuple[ClickInput, ...] = ()
    pointer_interactions: tuple[PointerInteractionInput, ...] = ()

    def contribution(self, backend: Any = None) -> WidgetContribution:
        return WidgetContribution(
            fields=tuple(
                item(backend) if callable(item) else item
                for item in self.field_builders
            ),
            field_retention=self.field_retention,
            geometries=tuple(
                item(backend) if callable(item) else item for item in self.geometries
            ),
            views=tuple(
                item(backend) if callable(item) else item for item in self.views
            ),
            operators=self.operators,
            visual_contributions=self.visual_contributions,
            panel_contribution_ids=self.panel_contribution_ids,
            panel=self.panel,
            controls=self.controls,
            selections=tuple(
                item(backend) if callable(item) else item
                for item in self.selections
            ),
            hit_targets=tuple(
                item(backend) if callable(item) else item
                for item in self.hit_targets
            ),
            clicks=tuple(
                item(backend) if callable(item) else item
                for item in self.clicks
            ),
            pointer_interactions=tuple(
                item(backend) if callable(item) else item
                for item in self.pointer_interactions
            ),
        )


def _merge_specs(
    target: dict[str, Any],
    specs: Sequence[Any],
    expected_type: type[Any],
    catalog_name: str,
) -> None:
    for spec in specs:
        if type(spec) is not expected_type:
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
    key_bindings: Sequence[KeyBindingInteraction] = (),
    backend: Any = None,
) -> AppSpec:
    """Merge source declarations into an immutable canonical AppSpec."""
    if isinstance(app_spec, StartupData):
        app_spec = app_spec.app_spec()

    fields = dict(app_spec.data.fields)
    geometries = dict(app_spec.data.geometries)
    views = dict(app_spec.view_catalog.views)
    operators = dict(app_spec.view_catalog.operators)
    visual_contributions = dict(app_spec.view_catalog.contributions)
    controls_by_id = dict(app_spec.interactions.controls)
    selections = dict(app_spec.interactions.selections)
    hit_targets = dict(app_spec.interactions.hit_targets)
    clicks = dict(app_spec.interactions.clicks)
    pointer_interactions = dict(app_spec.interactions.pointer_interactions)
    key_bindings_by_id = dict(app_spec.interactions.key_bindings)
    layouts = dict(app_spec.layout_catalog.layouts)
    layout = layouts[app_spec.layout_catalog.active]
    panels = list(layout.panels)
    panel_grid = list(layout.panel_grid)
    panel_ids = {panel.id for panel in panels}
    contributed_panel_visuals: dict[str, list[str]] = {}
    field_retention: dict[str, list[FieldRetentionSpec]] = {}

    for widget in panel_bindings:
        contribution = _widget_contribution(widget, backend)
        _merge_specs(fields, contribution.fields, FieldSpec, "field")
        for field_id, requirements in contribution.field_retention.items():
            field_retention.setdefault(field_id, []).extend(requirements)
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
            visual_contributions,
            contribution.visual_contributions,
            VisualContributionSpec,
            "visual contribution",
        )
        for panel_id, contribution_ids in contribution.panel_contribution_ids.items():
            contributed_panel_visuals.setdefault(panel_id, []).extend(
                contribution_ids
            )
        _merge_specs(
            controls_by_id,
            contribution.controls,
            ControlSpec,
            "control",
        )
        _merge_specs(
            selections,
            contribution.selections,
            SelectionSpec,
            "selection",
        )
        _merge_specs(
            hit_targets,
            contribution.hit_targets,
            HitTargetSpec,
            "hit target",
        )
        _merge_specs(
            clicks,
            contribution.clicks,
            ClickSpec,
            "click",
        )
        _merge_specs(
            pointer_interactions,
            contribution.pointer_interactions,
            PointerInteractionSpec,
            "pointer interaction",
        )
        panel = contribution.panel
        if panel is None:
            continue
        if type(panel) is not PanelSpec:
            raise TypeError(
                "widget panel contribution must be PanelSpec, "
                f"got {type(panel).__name__}"
            )
        if panel.id in panel_ids:
            raise ValueError(f"duplicate panel id {panel.id!r}")
        if contribution.controls:
            panel = replace(
                panel,
                control_ids=tuple(
                    dict.fromkeys(
                        (*panel.control_ids, *(spec.id for spec in contribution.controls))
                    )
                ),
            )
        panels.append(panel)
        panel_grid.append((panel.id,))
        panel_ids.add(panel.id)

    for control in controls:
        spec = control._control_spec()
        if spec.id in controls_by_id:
            raise ValueError(f"duplicate control id {spec.id!r}")
        controls_by_id[spec.id] = spec
    for key_binding in key_bindings:
        spec = key_binding._key_binding_spec()
        if spec.id in key_bindings_by_id:
            raise ValueError(f"duplicate key binding id {spec.id!r}")
        key_bindings_by_id[spec.id] = spec

    panel_index = {panel.id: index for index, panel in enumerate(panels)}
    for control in controls:
        index = panel_index.get(control.panel_id)
        if index is None:
            raise ValueError(
                f"control {control.name!r} references unknown controls panel "
                f"{control.panel_id!r}"
            )
        panel = panels[index]
        panels[index] = replace(
            panel,
            control_ids=tuple(dict.fromkeys((*panel.control_ids, control._control_id))),
        )

    for panel_id, contribution_ids in contributed_panel_visuals.items():
        index = panel_index.get(panel_id)
        if index is None:
            raise ValueError(
                f"visual contribution references unknown panel {panel_id!r}"
            )
        panel = panels[index]
        panels[index] = replace(
            panel,
            contribution_ids=tuple(
                dict.fromkeys((*panel.contribution_ids, *contribution_ids))
            ),
        )

    for field_id, requirements in field_retention.items():
        field_spec = fields.get(field_id)
        if field_spec is None:
            if field_id in operators:
                continue
            raise ValueError(
                f"field retention references unknown field {field_id!r}"
            )
        fields[field_id] = replace(
            field_spec,
            retention=tuple(
                dict.fromkeys((*field_spec.retention, *requirements))
            ),
        )

    layouts[app_spec.layout_catalog.active] = replace(
        layout,
        panels=tuple(panels),
        panel_grid=tuple(panel_grid),
    )
    return AppSpec(
        data=DataCatalog(fields=fields, geometries=geometries),
        view_catalog=ViewCatalog(
            views=views,
            operators=operators,
            contributions=visual_contributions,
        ),
        interactions=InteractionCatalog(
            controls=controls_by_id,
            key_bindings=key_bindings_by_id,
            selections=selections,
            hit_targets=hit_targets,
            clicks=clicks,
            pointer_interactions=pointer_interactions,
        ),
        layout_catalog=LayoutCatalog(
            layouts=layouts,
            active=app_spec.layout_catalog.active,
        ),
        metadata=app_spec.metadata,
    )


__all__ = [
    "FieldInput",
    "HitTargetInput",
    "ClickInput",
    "PointerInteractionInput",
    "GeometryInput",
    "SelectionInput",
    "SpecBinding",
    "ViewInput",
    "Binding",
    "WidgetContribution",
    "append_bindings_to_app_spec",
]
