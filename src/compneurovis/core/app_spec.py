from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from compneurovis.core._immutability import FrozenDict, freeze_spec_data
from compneurovis.core.controls import ControlSpec, KeyBindingSpec
from compneurovis.core.clicks import ClickSpec
from compneurovis.core.pointer_interactions import PointerInteractionSpec
from compneurovis.core.pointer import HitTargetSpec
from compneurovis.core.field import FieldSpec
from compneurovis.core.geometry import GeometrySpec
from compneurovis.core.operators import OperatorSpec
from compneurovis.core.references import (
    DEFAULT_FRAGMENT_ID,
    AppRef,
    app_ref,
    validate_local_id,
)
from compneurovis.core.selections import SelectionSpec
from compneurovis.core.specs import (
    PANEL_KIND_STANDALONE,  # noqa: F401 - re-exported for core import sites
    IdentifiedSpec,
    SpecBase,
)
from compneurovis.core.views import ViewSpec
from compneurovis.core.visual_contributions import VisualContributionSpec


def _freeze_identified_catalog(
    values: Mapping[str, Any],
    *,
    path: str,
    expected_type: type[Any],
) -> FrozenDict[str, Any]:
    frozen: dict[str, Any] = {}
    for key, spec in values.items():
        key = validate_local_id(key, path=f"{path} key")
        if type(spec) is not expected_type:
            raise TypeError(
                f"{path}[{key!r}] must be {expected_type.__name__}, "
                f"got {type(spec).__name__}"
            )
        spec_id = validate_local_id(
            getattr(spec, "id", None),
            path=f"{path}[{key!r}].id",
        )
        if key != spec_id:
            raise ValueError(
                f"{path} key {key!r} must match contained spec id {spec_id!r}"
            )
        frozen[key] = spec
    return FrozenDict(frozen)


def _same_catalog_entries(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
) -> bool:
    """Recognize the top-level aliases of an existing default fragment."""

    return left.keys() == right.keys() and all(
        left[key] is right[key] for key in left
    )


def _matches_default_fragment_aliases(
    data: "DataCatalog",
    views: "ViewCatalog",
    interactions: "InteractionCatalog",
    fragment: "AppFragmentSpec",
) -> bool:
    return (
        _same_catalog_entries(data.fields, fragment.data.fields)
        and _same_catalog_entries(data.geometries, fragment.data.geometries)
        and _same_catalog_entries(views.views, fragment.view_catalog.views)
        and _same_catalog_entries(views.operators, fragment.view_catalog.operators)
        and _same_catalog_entries(
            views.contributions, fragment.view_catalog.contributions
        )
        and _same_catalog_entries(
            interactions.controls, fragment.interactions.controls
        )
        and _same_catalog_entries(
            interactions.key_bindings, fragment.interactions.key_bindings
        )
        and _same_catalog_entries(
            interactions.selections, fragment.interactions.selections
        )
        and _same_catalog_entries(
            interactions.hit_targets, fragment.interactions.hit_targets
        )
        and _same_catalog_entries(
            interactions.clicks, fragment.interactions.clicks
        )
        and _same_catalog_entries(
            interactions.pointer_interactions,
            fragment.interactions.pointer_interactions,
        )
    )


@dataclass(frozen=True, slots=True)
class PanelSpec(IdentifiedSpec):
    kind: str
    view_ids: tuple[str | AppRef, ...] = ()
    control_ids: tuple[str | AppRef, ...] = ()
    contribution_ids: tuple[str | AppRef, ...] = ()
    title: str | None = None

    def __post_init__(self) -> None:
        kind = str(self.kind).strip()
        if not kind:
            raise ValueError("PanelSpec.kind cannot be empty")
        object.__setattr__(self, "kind", kind)
        for name in (
            "view_ids",
            "control_ids",
            "contribution_ids",
        ):
            object.__setattr__(
                self,
                name,
                tuple(
                    app_ref(value) if isinstance(value, AppRef) else str(value)
                    for value in getattr(self, name)
                ),
            )


@dataclass(frozen=True, slots=True)
class LayoutSpec(SpecBase):
    title: str = "CompNeuroVis"
    panels: tuple[PanelSpec, ...] = ()
    panel_grid: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        if any(type(panel) is not PanelSpec for panel in self.panels):
            raise TypeError("LayoutSpec.panels must contain only PanelSpec values")
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
        object.__setattr__(
            self,
            "fields",
            _freeze_identified_catalog(
                self.fields,
                path="DataCatalog.fields",
                expected_type=FieldSpec,
            ),
        )
        object.__setattr__(
            self,
            "geometries",
            _freeze_identified_catalog(
                self.geometries,
                path="DataCatalog.geometries",
                expected_type=GeometrySpec,
            ),
        )


@dataclass(frozen=True, slots=True)
class ViewCatalog(SpecBase):
    views: Mapping[str, ViewSpec] = field(default_factory=FrozenDict)
    operators: Mapping[str, OperatorSpec] = field(default_factory=FrozenDict)
    contributions: Mapping[str, VisualContributionSpec] = field(
        default_factory=FrozenDict
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "views",
            _freeze_identified_catalog(
                self.views,
                path="ViewCatalog.views",
                expected_type=ViewSpec,
            ),
        )
        object.__setattr__(
            self,
            "operators",
            _freeze_identified_catalog(
                self.operators,
                path="ViewCatalog.operators",
                expected_type=OperatorSpec,
            ),
        )
        object.__setattr__(
            self,
            "contributions",
            _freeze_identified_catalog(
                self.contributions,
                path="ViewCatalog.contributions",
                expected_type=VisualContributionSpec,
            ),
        )


@dataclass(frozen=True, slots=True)
class InteractionCatalog(SpecBase):
    controls: Mapping[str, ControlSpec] = field(default_factory=FrozenDict)
    key_bindings: Mapping[str, KeyBindingSpec] = field(default_factory=FrozenDict)
    selections: Mapping[str, SelectionSpec] = field(default_factory=FrozenDict)
    hit_targets: Mapping[str, HitTargetSpec] = field(default_factory=FrozenDict)
    clicks: Mapping[str, ClickSpec] = field(default_factory=FrozenDict)
    pointer_interactions: Mapping[str, PointerInteractionSpec] = field(
        default_factory=FrozenDict
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "controls",
            _freeze_identified_catalog(
                self.controls,
                path="InteractionCatalog.controls",
                expected_type=ControlSpec,
            ),
        )
        object.__setattr__(
            self,
            "key_bindings",
            _freeze_identified_catalog(
                self.key_bindings,
                path="InteractionCatalog.key_bindings",
                expected_type=KeyBindingSpec,
            ),
        )
        object.__setattr__(
            self,
            "selections",
            _freeze_identified_catalog(
                self.selections,
                path="InteractionCatalog.selections",
                expected_type=SelectionSpec,
            ),
        )
        object.__setattr__(
            self,
            "hit_targets",
            _freeze_identified_catalog(
                self.hit_targets,
                path="InteractionCatalog.hit_targets",
                expected_type=HitTargetSpec,
            ),
        )
        object.__setattr__(
            self,
            "clicks",
            _freeze_identified_catalog(
                self.clicks,
                path="InteractionCatalog.clicks",
                expected_type=ClickSpec,
            ),
        )
        object.__setattr__(
            self,
            "pointer_interactions",
            _freeze_identified_catalog(
                self.pointer_interactions,
                path="InteractionCatalog.pointer_interactions",
                expected_type=PointerInteractionSpec,
            ),
        )


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
        for layout_id, layout in layouts.items():
            if not isinstance(layout_id, str) or not layout_id.strip():
                raise TypeError("LayoutCatalog keys must be non-empty strings")
            if type(layout) is not LayoutSpec:
                raise TypeError(
                    f"LayoutCatalog.layouts[{layout_id!r}] must be LayoutSpec, "
                    f"got {type(layout).__name__}"
                )
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
        fragment_id = validate_local_id(
            self.id or DEFAULT_FRAGMENT_ID,
            path="AppFragmentSpec.id",
        )
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
            key_bindings=self.interactions.key_bindings,
                selections=self.interactions.selections,
                hit_targets=self.interactions.hit_targets,
                clicks=self.interactions.clicks,
                pointer_interactions=self.interactions.pointer_interactions,
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
        object.__setattr__(
            self,
            "metadata",
            freeze_spec_data(
                self.metadata,
                path=f"AppFragmentSpec[{fragment_id!r}].metadata",
            ),
        )

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
        panel.id for panel in panels if not panel.control_ids
    )
    interaction_panels = tuple(
        panel.id for panel in panels if panel.control_ids
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
            key_bindings=self.interactions.key_bindings,
            selections=self.interactions.selections,
            hit_targets=self.interactions.hit_targets,
            clicks=self.interactions.clicks,
            pointer_interactions=self.interactions.pointer_interactions,
        )
        layout_catalog = LayoutCatalog(
            layouts=self.layout_catalog.layouts,
            active=self.layout_catalog.active,
        )
        metadata = freeze_spec_data(self.metadata, path="AppSpec.metadata")

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
            for fragment_id, fragment in fragments.items():
                fragment_id = validate_local_id(
                    fragment_id,
                    path="AppSpec.fragments key",
                )
                if type(fragment) is not AppFragmentSpec:
                    raise TypeError(
                        f"AppSpec.fragments[{fragment_id!r}] must be "
                        f"AppFragmentSpec, got {type(fragment).__name__}"
                    )
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

            root_has_content = bool(
                data.fields
                or data.geometries
                or view_catalog.views
                or view_catalog.operators
                or view_catalog.contributions
                or interactions.controls
                or interactions.selections
                or interactions.hit_targets
                or interactions.clicks
                or interactions.pointer_interactions
            )
            if DEFAULT_FRAGMENT_ID in fragments:
                default_fragment = fragments[DEFAULT_FRAGMENT_ID]
                if root_has_content and not _matches_default_fragment_aliases(
                    data,
                    view_catalog,
                    interactions,
                    default_fragment,
                ):
                    raise ValueError(
                        "AppSpec default-fragment catalogs must be declared either "
                        "through top-level data/view_catalog/interactions or through "
                        "fragments['main'], not both"
                    )
                data = default_fragment.data
                view_catalog = default_fragment.view_catalog
                interactions = default_fragment.interactions
            elif root_has_content:
                fragments[DEFAULT_FRAGMENT_ID] = AppFragmentSpec(
                    id=DEFAULT_FRAGMENT_ID,
                    data=data,
                    view_catalog=view_catalog,
                    interactions=interactions,
                    layout_catalog=LayoutCatalog.single(
                        LayoutSpec(title=layout_catalog.active_layout().title)
                    ),
                )

        object.__setattr__(self, "data", data)
        object.__setattr__(self, "view_catalog", view_catalog)
        object.__setattr__(self, "interactions", interactions)
        object.__setattr__(self, "layout_catalog", layout_catalog)
        object.__setattr__(self, "metadata", metadata)
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

    def key_binding(self, ref: str | AppRef) -> KeyBindingSpec | None:
        resolved = app_ref(ref)
        return self.fragment(resolved.fragment_id).interactions.key_bindings.get(
            resolved.id
        )

    def selection(self, ref: str | AppRef) -> SelectionSpec | None:
        resolved = app_ref(ref)
        return self.fragment(resolved.fragment_id).interactions.selections.get(
            resolved.id
        )

    def click(self, ref: str | AppRef) -> ClickSpec | None:
        resolved = app_ref(ref)
        return self.fragment(resolved.fragment_id).interactions.clicks.get(
            resolved.id
        )

    def hit_target(self, ref: str | AppRef) -> HitTargetSpec | None:
        resolved = app_ref(ref)
        return self.fragment(resolved.fragment_id).interactions.hit_targets.get(
            resolved.id
        )

    def pointer_interaction(
        self, ref: str | AppRef
    ) -> PointerInteractionSpec | None:
        resolved = app_ref(ref)
        return self.fragment(
            resolved.fragment_id
        ).interactions.pointer_interactions.get(resolved.id)

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

    def iter_key_bindings(self):
        for fragment in self.fragments.values():
            for local_id, binding in fragment.interactions.key_bindings.items():
                yield AppRef(local_id, fragment.id), binding

    def iter_selections(self):
        for fragment in self.fragments.values():
            for local_id, selection in fragment.interactions.selections.items():
                yield AppRef(local_id, fragment.id), selection

    def iter_clicks(self):
        for fragment in self.fragments.values():
            for local_id, interaction in fragment.interactions.clicks.items():
                yield AppRef(local_id, fragment.id), interaction

    def iter_hit_targets(self):
        for fragment in self.fragments.values():
            for local_id, target in fragment.interactions.hit_targets.items():
                yield AppRef(local_id, fragment.id), target

    def iter_pointer_interactions(self):
        for fragment in self.fragments.values():
            for local_id, interaction in (
                fragment.interactions.pointer_interactions.items()
            ):
                yield AppRef(local_id, fragment.id), interaction
