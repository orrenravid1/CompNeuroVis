"""Shared morphology widget lowering."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Callable

from compneurovis.backends.interaction import (
    SELECTED_ENTITY_ID_KEY,
    SELECTED_ENTITY_IDS_KEY,
    _selection_to_internal,
)
from compneurovis.core.app_spec import PANEL_KIND_VIEW_3D, PanelSpec
from compneurovis.core.geometry import MorphologyGeometrySpec
from compneurovis.core.views import ExtensionViewSpec
from compneurovis.inline._ids import slug
from compneurovis.inline.compiler import WidgetContribution
from compneurovis.inline.refs import MorphologyRef, SelectionRef, bind
from compneurovis.inline.widgets.api import Widget


@dataclass
class MorphologyBinding:
    view_id: str
    panel_id: str
    title: Any
    geometry_id: str | Callable[[Any], str]
    color_field_id: str | None = None
    entity_dim: str = "segment"
    sample_dim: str | None = None
    selectable: bool = True
    style: Mapping[str, Any] = field(default_factory=dict)

    def contribution(self, backend: Any = None) -> WidgetContribution:
        return WidgetContribution(
            views=(self.view_spec(backend),),
            panel=self.panel_spec(),
        )

    def view_spec(self, backend: Any = None) -> ExtensionViewSpec:
        # A morphology is a first-class extension view (kind="morphology") in a
        # VIEW_3D panel; the frontend reconstructs its typed render-config.
        geometry_id = (
            self.geometry_id(backend)
            if callable(self.geometry_id)
            else self.geometry_id
        )
        style = {key: bind(value) for key, value in self.style.items()}
        max_refresh_hz = style.pop("max_refresh_hz", None)
        inputs = {"color": self.color_field_id} if self.color_field_id else {}
        return ExtensionViewSpec(
            id=self.view_id,
            title=bind(self.title),
            kind="morphology",
            inputs=inputs,
            properties={
                "geometry_id": geometry_id,
                "entity_dim": self.entity_dim,
                "sample_dim": self.sample_dim,
                "selectable": self.selectable,
                **style,
            },
            max_refresh_hz=max_refresh_hz,
            panel_kind=PANEL_KIND_VIEW_3D,
        )

    def panel_spec(self) -> PanelSpec:
        return PanelSpec(
            id=self.panel_id,
            kind=PANEL_KIND_VIEW_3D,
            view_ids=(self.view_id,),
        )


@dataclass(frozen=True, slots=True)
class Morphology(Widget[MorphologyRef]):
    """Reusable custom-morphology widget accepted by ``source.add()``."""

    geometry: MorphologyGeometrySpec
    name: str = "Morphology"
    values: Any = None
    read: Callable[[], Any] | None = None
    unit: str | None = None
    color_limits: tuple[float, float] | None = None
    color_map: str = "scalar"
    color_norm: str = "auto"
    background_color: Any = "white"
    max_refresh_hz: float | None = None
    selected: Any = None
    selectable: bool = True
    select_multiple: bool = False
    panel: bool = True

    def declare(self, context) -> MorphologyRef:
        if not isinstance(self.geometry, MorphologyGeometrySpec):
            raise TypeError("morphology expects MorphologyGeometrySpec geometry")
        if self.select_multiple and not self.selectable:
            raise ValueError(
                "morphology(select_multiple=True) requires selectable=True"
            )
        if self.values is not None and self.read is not None:
            raise ValueError("morphology accepts values=... or read=..., not both")

        name_slug = slug(self.name)
        panel_id = f"{name_slug}-panel"
        color_field_id = None
        field_builders = ()
        if self.values is not None or self.read is not None:
            data = context._declare_field(
                field_id=f"{name_slug}_values",
                dim="segment",
                labels=self.geometry.entity_ids,
                values=self.values,
                read=self.read,
                unit=self.unit,
            )
            color_field_id = data.field_id
            field_builders = (lambda backend, binding=data: binding.field_spec(),)

        context._register_geometry(self.geometry, field_builders=field_builders)
        selection_key = SELECTED_ENTITY_IDS_KEY
        context._set_selection_mode(selection_key, self.select_multiple)
        if self.selected is not None:
            selected_ids = _selection_to_internal(
                self.selected,
                select_multiple=self.select_multiple,
            )
            context._set_initial_value(selection_key, selected_ids)
            active_id = selected_ids[0] if selected_ids else None
            context._set_initial_value(SELECTED_ENTITY_ID_KEY, active_id)
            if active_id is not None:
                context._set_initial_value(
                    "selected_entity_label",
                    self.geometry.label_for(active_id),
                )

        context._register_morphology(
            MorphologyBinding(
                view_id=name_slug,
                panel_id=panel_id,
                title=self.name,
                geometry_id=self.geometry.id,
                color_field_id=color_field_id,
                selectable=self.selectable,
                style={
                    "color_map": self.color_map,
                    "color_limits": self.color_limits,
                    "color_norm": self.color_norm,
                    "background_color": self.background_color,
                    "max_refresh_hz": self.max_refresh_hz,
                },
            ),
            panel=self.panel,
        )
        return MorphologyRef(
            id=panel_id,
            selected=SelectionRef(selection_key, self.select_multiple),
        )


__all__ = ["Morphology", "MorphologyBinding"]
