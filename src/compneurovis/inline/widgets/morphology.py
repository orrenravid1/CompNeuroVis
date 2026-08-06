"""Shared morphology widget lowering."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Callable

from compneurovis.core.app_spec import PANEL_KIND_VIEW_3D, PanelSpec
from compneurovis.core.geometry import MorphologyGeometrySpec
from compneurovis.core.selections import SelectionSpec
from compneurovis.core.views import ExtensionViewSpec
from compneurovis.inline._ids import slug
from compneurovis.inline.compiler import WidgetContribution
from compneurovis.inline.refs import GeometryRef, MorphologyRef, bind
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
    selection_id: str = ""
    selection_initial: tuple[str, ...] = ()
    selection_multiple: bool = False
    selectable: bool = True
    selection_declared: bool = False
    style: Mapping[str, Any] = field(default_factory=dict)

    def contribution(self, backend: Any = None) -> WidgetContribution:
        geometry_id = self._geometry_id(backend)
        selections = (
            ()
            if self.selection_declared
            else (
                SelectionSpec(
                    id=self.selection_id,
                    geometry_id=geometry_id,
                    initial=self.selection_initial,
                    multiple=self.selection_multiple,
                ),
            )
        )
        return WidgetContribution(
            views=(self.view_spec(backend, geometry_id=geometry_id),),
            selections=selections,
            panel=self.panel_spec(),
        )

    def _geometry_id(self, backend: Any = None) -> str:
        return (
            self.geometry_id(backend)
            if callable(self.geometry_id)
            else self.geometry_id
        )

    def view_spec(
        self,
        backend: Any = None,
        *,
        geometry_id: str | None = None,
    ) -> ExtensionViewSpec:
        # A morphology is a first-class extension view (kind="morphology") in a
        # VIEW_3D panel; the frontend reconstructs its typed render-config.
        geometry_id = geometry_id or self._geometry_id(backend)
        style = {key: bind(value) for key, value in self.style.items()}
        max_refresh_hz = style.pop("max_refresh_hz", None)
        inputs = {"color": self.color_field_id} if self.color_field_id else {}
        return ExtensionViewSpec(
            id=self.view_id,
            title=bind(self.title),
            kind="morphology",
            inputs=inputs,
            geometries={"morphology": geometry_id},
            selections=(
                {"entities": self.selection_id}
                if self.selectable
                else {}
            ),
            properties={
                "entity_dim": self.entity_dim,
                "sample_dim": self.sample_dim,
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
        selection = context.selection(
            f"{self.name} entities",
            geometry=GeometryRef(self.geometry.id, "morphology"),
            initial=self.selected,
            multiple=self.select_multiple,
        )

        context._register_morphology(
            MorphologyBinding(
                view_id=name_slug,
                panel_id=panel_id,
                title=self.name,
                geometry_id=self.geometry.id,
                color_field_id=color_field_id,
                selection_id=selection.id,
                selection_multiple=self.select_multiple,
                selectable=self.selectable,
                selection_declared=True,
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
            selected=selection,
        )


__all__ = ["Morphology", "MorphologyBinding"]
