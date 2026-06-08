from __future__ import annotations

from dataclasses import replace
from typing import Any

from compneurovis.core.app_spec import (
    AppSpec,
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

    Two members, two tiers:

    - ``spec``: the actor-local structural snapshot. Runtime structural
      updates replace this with a new immutable AppSpec. The declared startup
      AppSpec remains immutable and unmodified.

    - ``fields``: the live value views, derived from the declaration's
      ``FieldSpec`` entries via ``materialize()``. FieldAppend/FieldReplace
      fold here. Field values do not live in AppSpec.
    """

    __slots__ = ("spec", "fields", "metadata", "active_layout_id")

    def __init__(self, seed: AppSpec) -> None:
        self.spec = seed
        self.fields: dict[str, Field] = {
            field_id: field_spec.materialize()
            for field_id, field_spec in seed.data.fields.items()
        }
        # Live metadata: seeded from the declaration, then folded by
        # AppMetadataPatch. The seed's AppSpec.metadata stays the declared
        # initial value.
        self.metadata: dict = dict(seed.metadata)
        # Live active-layout selection. LayoutCatalog.active is the declared
        # default; the current selection is projection state.
        self.active_layout_id: str = seed.layout_catalog.active

    def active_layout(self) -> LayoutSpec:
        return self.spec.layout_catalog.layouts[self.active_layout_id]

    def replace_view(self, view_id: str, updates: dict[str, Any]) -> None:
        current = self.spec.view_catalog.views.get(view_id)
        if current is None:
            raise KeyError(f"Unknown view id {view_id!r}")
        views = dict(self.spec.view_catalog.views)
        views[view_id] = replace(current, **updates)
        self._replace_view_catalog(views=views)

    def replace_operator(self, operator_id: str, updates: dict[str, Any]) -> None:
        current = self.spec.view_catalog.operators.get(operator_id)
        if current is None:
            raise KeyError(f"Unknown operator id {operator_id!r}")
        operators = dict(self.spec.view_catalog.operators)
        operators[operator_id] = replace(current, **updates)
        self._replace_view_catalog(operators=operators)

    def replace_control(self, control_id: str, updates: dict[str, Any]) -> None:
        current = self.spec.interactions.controls.get(control_id)
        if current is None:
            raise KeyError(f"Unknown control id {control_id!r}")
        controls = dict(self.spec.interactions.controls)
        controls[control_id] = replace(current, **updates)
        self.spec = AppSpec(
            data=self.spec.data,
            view_catalog=self.spec.view_catalog,
            interactions=InteractionCatalog(
                controls=controls,
                actions=self.spec.interactions.actions,
            ),
            layout_catalog=self.spec.layout_catalog,
            metadata=self.spec.metadata,
        )

    def patch_panel(self, panel_id: str, **changes: Any) -> bool:
        layout = self.active_layout()
        panels = list(layout.panels)
        for index, panel in enumerate(panels):
            if panel.id != panel_id:
                continue
            panels[index] = replace(panel, **changes)
            self.replace_active_layout_panels(
                tuple(panels),
                layout.panel_grid,
            )
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
        )

    def _replace_view_catalog(
        self,
        *,
        views: dict[str, Any] | None = None,
        operators: dict[str, Any] | None = None,
    ) -> None:
        self.spec = AppSpec(
            data=DataCatalog(
                fields=self.spec.data.fields,
                geometries=self.spec.data.geometries,
            ),
            view_catalog=ViewCatalog(
                views=self.spec.view_catalog.views if views is None else views,
                operators=self.spec.view_catalog.operators if operators is None else operators,
            ),
            interactions=self.spec.interactions,
            layout_catalog=self.spec.layout_catalog,
            metadata=self.spec.metadata,
        )


__all__ = ["AppProjection"]
