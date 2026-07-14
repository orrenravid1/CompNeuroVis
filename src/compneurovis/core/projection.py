from __future__ import annotations

from dataclasses import replace
from typing import Any

from compneurovis.core.app_spec import (
    AppFragmentSpec,
    AppRef,
    app_ref,
    AppSpec,
    DEFAULT_FRAGMENT_ID,
    DataCatalog,
    InteractionCatalog,
    LayoutCatalog,
    LayoutSpec,
    PanelSpec,
    ViewCatalog,
)
from compneurovis.core.field import Field


class AppProjection:
    """Actor-local read model derived from AppSpec plus runtime updates.

    Structural definitions remain in AppSpec fragments. Live field values are
    keyed by AppRef so independent fragments can use the same local field ids.
    """

    __slots__ = ("spec", "fields", "metadata", "active_layout_id")

    def __init__(self, seed: AppSpec) -> None:
        self.spec = seed
        self.fields: dict[AppRef, Field] = {
            ref: field_spec.materialize()
            for ref, field_spec in seed.iter_field_specs()
        }
        self.metadata: dict = dict(seed.metadata)
        self.active_layout_id: str = seed.layout_catalog.active

    def active_layout(self) -> LayoutSpec:
        return self.spec.layout_catalog.layouts[self.active_layout_id]

    def ref(self, value: str | AppRef, *, fragment_id: str = DEFAULT_FRAGMENT_ID) -> AppRef:
        return app_ref(value, fragment_id=fragment_id)

    def field(self, ref: str | AppRef, *, fragment_id: str = DEFAULT_FRAGMENT_ID) -> Field | None:
        return self.fields.get(app_ref(ref, fragment_id=fragment_id))

    def replace_field(self, ref: str | AppRef, field: Field, *, fragment_id: str = DEFAULT_FRAGMENT_ID) -> None:
        self.fields[app_ref(ref, fragment_id=fragment_id)] = field

    def replace_view(self, view_id: str | AppRef, updates: dict[str, Any]) -> None:
        ref = app_ref(view_id)
        fragment = self.spec.fragment(ref.fragment_id)
        current = fragment.view_catalog.views.get(ref.id)
        if current is None:
            raise KeyError(f"Unknown view id {str(ref)!r}")
        views = dict(fragment.view_catalog.views)
        views[ref.id] = replace(current, **updates)
        self._replace_fragment(fragment, view_catalog=ViewCatalog(views=views, operators=fragment.view_catalog.operators))

    def replace_operator(self, operator_id: str | AppRef, updates: dict[str, Any]) -> None:
        ref = app_ref(operator_id)
        fragment = self.spec.fragment(ref.fragment_id)
        current = fragment.view_catalog.operators.get(ref.id)
        if current is None:
            raise KeyError(f"Unknown operator id {str(ref)!r}")
        operators = dict(fragment.view_catalog.operators)
        operators[ref.id] = replace(current, **updates)
        self._replace_fragment(fragment, view_catalog=ViewCatalog(views=fragment.view_catalog.views, operators=operators))

    def replace_control(self, control_id: str | AppRef, updates: dict[str, Any]) -> None:
        ref = app_ref(control_id)
        fragment = self.spec.fragment(ref.fragment_id)
        current = fragment.interactions.controls.get(ref.id)
        if current is None:
            raise KeyError(f"Unknown control id {str(ref)!r}")
        controls = dict(fragment.interactions.controls)
        controls[ref.id] = replace(current, **updates)
        self._replace_fragment(
            fragment,
            interactions=InteractionCatalog(
                controls=controls,
                actions=fragment.interactions.actions,
            ),
        )

    def patch_panel(self, panel_id: str, **changes: Any) -> bool:
        layout = self.active_layout()
        panels = list(layout.panels)
        for index, panel in enumerate(panels):
            if panel.id != panel_id:
                continue
            panels[index] = replace(panel, **changes)
            self.replace_active_layout_panels(tuple(panels), layout.panel_grid)
            return True
        return False

    def replace_active_layout_panels(
        self,
        panels: tuple[PanelSpec, ...],
        panel_grid: tuple[tuple[str, ...], ...],
    ) -> None:
        current = self.active_layout()
        layouts = dict(self.spec.layout_catalog.layouts)
        layouts[self.active_layout_id] = LayoutSpec(
            title=current.title,
            panels=tuple(panels),
            panel_grid=tuple(tuple(row) for row in panel_grid),
        )
        self.spec = AppSpec(
            data=self.spec.data,
            view_catalog=self.spec.view_catalog,
            interactions=self.spec.interactions,
            layout_catalog=LayoutCatalog(layouts=layouts, active=self.spec.layout_catalog.active),
            metadata=self.spec.metadata,
            fragments=self.spec.fragments,
        )

    def _replace_fragment(
        self,
        fragment: AppFragmentSpec,
        *,
        data: DataCatalog | None = None,
        view_catalog: ViewCatalog | None = None,
        interactions: InteractionCatalog | None = None,
        layout_catalog: LayoutCatalog | None = None,
    ) -> None:
        fragments = dict(self.spec.fragments)
        fragments[fragment.id] = AppFragmentSpec(
            id=fragment.id,
            data=fragment.data if data is None else data,
            view_catalog=fragment.view_catalog if view_catalog is None else view_catalog,
            interactions=fragment.interactions if interactions is None else interactions,
            layout_catalog=fragment.layout_catalog if layout_catalog is None else layout_catalog,
            metadata=fragment.metadata,
        )
        self.spec = AppSpec(
            data=self.spec.data,
            view_catalog=self.spec.view_catalog,
            interactions=self.spec.interactions,
            layout_catalog=self.spec.layout_catalog,
            metadata=self.spec.metadata,
            fragments=fragments,
        )


__all__ = ["AppProjection"]
