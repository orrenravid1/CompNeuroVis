from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

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
    default_panel_grid,
)
from compneurovis.core.app_fragment import (
    _integrate_fragment_panel,
    _integrated_panel_id,
)
from compneurovis.core.field import Field


class AppProjection:
    """Actor-local read model derived from AppSpec plus runtime updates.

    Structural definitions remain in AppSpec fragments. Live field values are
    keyed by AppRef so independent fragments can use the same local field ids.
    """

    __slots__ = ("spec", "fields", "active_layout_id")

    def __init__(self, seed: AppSpec) -> None:
        self.spec = seed
        self.fields: dict[AppRef, Field] = {
            ref: field_spec.materialize()
            for ref, field_spec in seed.iter_field_specs()
        }
        self.active_layout_id: str = seed.layout_catalog.active

    @property
    def metadata(self) -> Mapping[str, Any]:
        """Current global app metadata, owned by the live immutable spec."""

        return self.spec.metadata

    def patch_metadata(self, updates: Mapping[str, Any]) -> None:
        metadata = dict(self.spec.metadata)
        metadata.update(updates)
        self.spec = AppSpec(
            layout_catalog=self.spec.layout_catalog,
            metadata=metadata,
            fragments=self.spec.fragments,
        )

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
        self._replace_fragment(
            fragment,
            view_catalog=ViewCatalog(
                views=views,
                operators=fragment.view_catalog.operators,
                contributions=fragment.view_catalog.contributions,
            ),
        )

    def replace_operator(self, operator_id: str | AppRef, updates: dict[str, Any]) -> None:
        ref = app_ref(operator_id)
        fragment = self.spec.fragment(ref.fragment_id)
        current = fragment.view_catalog.operators.get(ref.id)
        if current is None:
            raise KeyError(f"Unknown operator id {str(ref)!r}")
        operators = dict(fragment.view_catalog.operators)
        operators[ref.id] = replace(current, **updates)
        self._replace_fragment(
            fragment,
            view_catalog=ViewCatalog(
                views=fragment.view_catalog.views,
                operators=operators,
                contributions=fragment.view_catalog.contributions,
            ),
        )

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
                key_bindings=fragment.interactions.key_bindings,
                selections=fragment.interactions.selections,
                hit_targets=fragment.interactions.hit_targets,
                clicks=fragment.interactions.clicks,
                pointer_interactions=fragment.interactions.pointer_interactions,
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
        resolved_grid = panel_grid or default_panel_grid(tuple(panels))
        layouts = dict(self.spec.layout_catalog.layouts)
        layouts[self.active_layout_id] = LayoutSpec(
            title=current.title,
            panels=tuple(panels),
            panel_grid=tuple(tuple(row) for row in resolved_grid),
        )
        self.spec = AppSpec(
            layout_catalog=LayoutCatalog(layouts=layouts, active=self.spec.layout_catalog.active),
            metadata=self.spec.metadata,
            fragments=self.spec.fragments,
        )

    def replace_fragment_layout_panels(
        self,
        fragment_id: str,
        panels: tuple[PanelSpec, ...],
        panel_grid: tuple[tuple[str, ...], ...],
    ) -> None:
        """Replace one source-owned layout without disturbing peer fragments."""

        fragment = self.spec.fragment(fragment_id)
        local_current = fragment.active_layout()
        local_grid = panel_grid or default_panel_grid(tuple(panels))
        local_layouts = dict(fragment.layout_catalog.layouts)
        local_layouts[fragment.layout_catalog.active] = LayoutSpec(
            title=local_current.title,
            panels=tuple(panels),
            panel_grid=tuple(tuple(row) for row in local_grid),
        )
        updated_fragment = AppFragmentSpec(
            id=fragment.id,
            data=fragment.data,
            view_catalog=fragment.view_catalog,
            interactions=fragment.interactions,
            layout_catalog=LayoutCatalog(
                layouts=local_layouts,
                active=fragment.layout_catalog.active,
            ),
            metadata=fragment.metadata,
        )

        old_panel_ids = {
            _integrated_panel_id(fragment_id, panel.id)
            for panel in local_current.panels
        }
        integrated_panels = tuple(
            _integrate_fragment_panel(panel, fragment_id) for panel in panels
        )

        global_current = self.active_layout()
        remaining_panels = [
            panel for panel in global_current.panels if panel.id not in old_panel_ids
        ]
        insertion_index = next(
            (
                index
                for index, panel in enumerate(global_current.panels)
                if panel.id in old_panel_ids
            ),
            len(global_current.panels),
        )
        insertion_index -= sum(
            panel.id in old_panel_ids
            for panel in global_current.panels[:insertion_index]
        )
        remaining_panels[insertion_index:insertion_index] = integrated_panels

        remaining_rows: list[tuple[str, ...]] = []
        row_insertion_index: int | None = None
        for row in global_current.panel_grid:
            owns_cell = any(panel_id in old_panel_ids for panel_id in row)
            if owns_cell and row_insertion_index is None:
                row_insertion_index = len(remaining_rows)
            retained = tuple(
                panel_id for panel_id in row if panel_id not in old_panel_ids
            )
            if retained:
                remaining_rows.append(retained)
        if row_insertion_index is None:
            row_insertion_index = len(remaining_rows)
        integrated_rows = [
            tuple(_integrated_panel_id(fragment_id, panel_id) for panel_id in row)
            for row in local_grid
        ]
        remaining_rows[row_insertion_index:row_insertion_index] = integrated_rows

        global_layouts = dict(self.spec.layout_catalog.layouts)
        global_layouts[self.active_layout_id] = LayoutSpec(
            title=global_current.title,
            panels=tuple(remaining_panels),
            panel_grid=tuple(remaining_rows),
        )
        fragments = dict(self.spec.fragments)
        fragments[fragment_id] = updated_fragment
        self.spec = AppSpec(
            layout_catalog=LayoutCatalog(
                layouts=global_layouts,
                active=self.spec.layout_catalog.active,
            ),
            metadata=self.spec.metadata,
            fragments=fragments,
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
            layout_catalog=self.spec.layout_catalog,
            metadata=self.spec.metadata,
            fragments=fragments,
        )
__all__ = ["AppProjection"]
