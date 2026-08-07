from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from compneurovis.core._immutability import FrozenDict
from compneurovis.core.controls import ActionSpec, ControlSpec
from compneurovis.core.field import FieldSpec
from compneurovis.core.geometry import GeometrySpec
from compneurovis.core.operators import OperatorSpec
from compneurovis.core.references import DEFAULT_FRAGMENT_ID, AppRef, app_ref
from compneurovis.core.selections import SelectionSpec
from compneurovis.core.specs import (
    PANEL_KIND_STANDALONE,  # noqa: F401 - re-exported for core import sites
    IdentifiedSpec,
    SpecBase,
)
from compneurovis.core.views import ViewSpec
from compneurovis.core.visual_contributions import VisualContributionSpec


@dataclass(frozen=True, slots=True)
class PanelSpec(IdentifiedSpec):
    kind: str
    view_ids: tuple[str | AppRef, ...] = ()
    control_ids: tuple[str | AppRef, ...] = ()
    action_ids: tuple[str | AppRef, ...] = ()
    contribution_ids: tuple[str | AppRef, ...] = ()
    title: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "view_ids", tuple(self.view_ids))
        object.__setattr__(self, "control_ids", tuple(self.control_ids))
        object.__setattr__(self, "action_ids", tuple(self.action_ids))
        object.__setattr__(self, "contribution_ids", tuple(self.contribution_ids))


@dataclass(frozen=True, slots=True)
class LayoutSpec(SpecBase):
    title: str = "CompNeuroVis"
    panels: tuple[PanelSpec, ...] = ()
    panel_grid: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "panels", tuple(self.panels))
        object.__setattr__(
            self, "panel_grid", tuple(tuple(row) for row in self.panel_grid)
        )

    def panels_of_kind(self, kind: str) -> tuple[PanelSpec, ...]:
        return tuple(panel for panel in self.panels if panel.kind == kind)

    def panel(self, panel_id: str) -> PanelSpec | None:
        for panel in self.panels:
            if panel.id == panel_id:
                return panel
        return None

    def panel_for_view(
        self, view_id: str | AppRef, *, kind: str | None = None
    ) -> PanelSpec | None:
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
    contributions: Mapping[str, VisualContributionSpec] = field(
        default_factory=FrozenDict
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "views", FrozenDict(self.views))
        object.__setattr__(self, "operators", FrozenDict(self.operators))
        object.__setattr__(self, "contributions", FrozenDict(self.contributions))


@dataclass(frozen=True, slots=True)
class InteractionCatalog(SpecBase):
    controls: Mapping[str, ControlSpec] = field(default_factory=FrozenDict)
    actions: Mapping[str, ActionSpec] = field(default_factory=FrozenDict)
    selections: Mapping[str, SelectionSpec] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "controls", FrozenDict(self.controls))
        object.__setattr__(self, "actions", FrozenDict(self.actions))
        object.__setattr__(self, "selections", FrozenDict(self.selections))


@dataclass(frozen=True, slots=True)
class LayoutCatalog(SpecBase):
    layouts: Mapping[str, LayoutSpec] = field(
        default_factory=lambda: FrozenDict({"default": LayoutSpec()})
    )
    active: str = "default"

    def __post_init__(self) -> None:
        layouts = dict(self.layouts)
        if not self.layouts:
            layouts = {"default": LayoutSpec()}
            object.__setattr__(self, "active", "default")
        object.__setattr__(self, "layouts", FrozenDict(layouts))
        if self.active not in self.layouts:
            raise ValueError(
                f"Active layout {self.active!r} is not present in LayoutCatalog.layouts"
            )

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
                contributions=self.view_catalog.contributions,
            ),
        )
        object.__setattr__(
            self,
            "interactions",
            InteractionCatalog(
                controls=self.interactions.controls,
                actions=self.interactions.actions,
                selections=self.interactions.selections,
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
    additional_panels: tuple[PanelSpec, ...] = (),
    title: str = "CompNeuroVis",
) -> LayoutSpec:
    """Build a default layout from views plus explicitly authored other panels.

    A view declares its own panel host kind. Viewless interaction or contribution
    panels have no canonical host kind to infer, so callers provide their complete
    neutral ``PanelSpec`` declarations through ``additional_panels``.
    """

    panels: list[PanelSpec] = []
    for view in views.values():
        # A view declares its own panel kind (``view.panel_kind``) — no isinstance
        # ladder, so a third-party view type gets its default panel for free.
        panels.append(
            PanelSpec(
                id=f"{view.id}-panel",
                kind=view.panel_kind,
                view_ids=(view.id,),
            )
        )

    panels.extend(additional_panels)

    return LayoutSpec(
        title=title,
        panels=tuple(panels),
        panel_grid=default_panel_grid(tuple(panels)),
    )


def build_default_layout_catalog(
    *,
    views: dict[str, ViewSpec],
    additional_panels: tuple[PanelSpec, ...] = (),
    title: str = "CompNeuroVis",
) -> LayoutCatalog:
    return LayoutCatalog.single(
        build_default_layout(
            views=views,
            additional_panels=additional_panels,
            title=title,
        )
    )


def default_panel_grid(panels: tuple[PanelSpec, ...]) -> tuple[tuple[str, ...], ...]:
    content_panels = tuple(
        panel.id for panel in panels if not (panel.control_ids or panel.action_ids)
    )
    interaction_panels = tuple(
        panel.id for panel in panels if panel.control_ids or panel.action_ids
    )
    rows: list[tuple[str, ...]] = []
    if content_panels:
        rows.append(content_panels)
    rows.extend((panel_id,) for panel_id in interaction_panels)
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
            contributions=self.view_catalog.contributions,
        )
        interactions = InteractionCatalog(
            controls=self.interactions.controls,
            actions=self.interactions.actions,
            selections=self.interactions.selections,
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
        from compneurovis.core.app_validation import validate_app_spec

        validate_app_spec(self)

    def fragment(self, fragment_id: str = DEFAULT_FRAGMENT_ID) -> AppFragmentSpec:
        return self.fragments[fragment_id]

    def ref(
        self, value: str | AppRef, *, fragment_id: str = DEFAULT_FRAGMENT_ID
    ) -> AppRef:
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
        return self.fragment(resolved.fragment_id).view_catalog.operators.get(
            resolved.id
        )

    def visual_contribution(
        self, ref: str | AppRef
    ) -> VisualContributionSpec | None:
        resolved = app_ref(ref)
        return self.fragment(resolved.fragment_id).view_catalog.contributions.get(
            resolved.id
        )

    def control(self, ref: str | AppRef) -> ControlSpec | None:
        resolved = app_ref(ref)
        return self.fragment(resolved.fragment_id).interactions.controls.get(
            resolved.id
        )

    def action(self, ref: str | AppRef) -> ActionSpec | None:
        resolved = app_ref(ref)
        return self.fragment(resolved.fragment_id).interactions.actions.get(resolved.id)

    def selection(self, ref: str | AppRef) -> SelectionSpec | None:
        resolved = app_ref(ref)
        return self.fragment(resolved.fragment_id).interactions.selections.get(
            resolved.id
        )

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

    def iter_visual_contributions(self):
        for fragment in self.fragments.values():
            for local_id, contribution in fragment.view_catalog.contributions.items():
                yield AppRef(local_id, fragment.id), contribution

    def iter_controls(self):
        for fragment in self.fragments.values():
            for local_id, control in fragment.interactions.controls.items():
                yield AppRef(local_id, fragment.id), control

    def iter_actions(self):
        for fragment in self.fragments.values():
            for local_id, action in fragment.interactions.actions.items():
                yield AppRef(local_id, fragment.id), action

    def iter_selections(self):
        for fragment in self.fragments.values():
            for local_id, selection in fragment.interactions.selections.items():
                yield AppRef(local_id, fragment.id), selection
