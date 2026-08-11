"""Morphology widget authored through public context primitives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from compneurovis.inline._ids import slug
from compneurovis.inline.refs import (
    DataRef,
    GeometryRef,
    MorphologyRef,
    PanelRef,
    SelectionRef,
)
from compneurovis.inline.widgets.api import Widget
from compneurovis.geometries.morphology import MorphologyGeometry


DEFAULT_MORPHOLOGY_CAMERA_ORBIT_SENSITIVITY = 1.0
DEFAULT_MORPHOLOGY_CAMERA_PAN_SENSITIVITY = 100.0
DEFAULT_MORPHOLOGY_CAMERA_ZOOM_SENSITIVITY = 1.2


def _declare_morphology_view(
    context,
    *,
    name: str,
    geometry: GeometryRef,
    color: DataRef | None = None,
    entity_dim: str = "segment",
    sample_dim: str | None = None,
    selection_initial: Any = None,
    selection_multiple: bool = False,
    selectable: bool = True,
    panel: bool = True,
    color_map: str = "scalar",
    color_limits: Any = None,
    color_norm: str = "auto",
    background_color: Any = "white",
    max_refresh_hz: float | None = None,
    camera_orbit_sensitivity: float = DEFAULT_MORPHOLOGY_CAMERA_ORBIT_SENSITIVITY,
    camera_pan_sensitivity: float = DEFAULT_MORPHOLOGY_CAMERA_PAN_SENSITIVITY,
    camera_zoom_sensitivity: float = DEFAULT_MORPHOLOGY_CAMERA_ZOOM_SENSITIVITY,
) -> tuple[PanelRef, SelectionRef]:
    """Declare the shared morphology view/selection composition."""
    panel_id = f"{slug(name)}-panel"
    selection = context.selection(
        f"{name} entities",
        geometry=geometry,
        initial=selection_initial,
        multiple=selection_multiple,
    )
    panel_ref = PanelRef(panel_id)
    if panel:
        panel_ref = context.view(
            "morphology",
            name,
            inputs={} if color is None else {"color": color},
            geometries={"morphology": geometry},
            selections={"entities": selection} if selectable else {},
            properties={
                "entity_dim": entity_dim,
                "sample_dim": sample_dim,
                "color_map": color_map,
                "color_limits": color_limits,
                "color_norm": color_norm,
                "background_color": background_color,
                "camera_orbit_sensitivity": camera_orbit_sensitivity,
                "camera_pan_sensitivity": camera_pan_sensitivity,
                "camera_zoom_sensitivity": camera_zoom_sensitivity,
            },
            title=name,
            panel_id=panel_id,
            panel_kind="scene_3d",
            max_refresh_hz=max_refresh_hz,
        )
    return panel_ref, selection


@dataclass(frozen=True, slots=True)
class Morphology(Widget[MorphologyRef]):
    """Reusable custom-morphology widget accepted by ``source.add()``."""

    geometry: MorphologyGeometry | GeometryRef
    name: str = "Morphology"
    color: DataRef | None = None
    values: Any = None
    read: Callable[[], Any] | None = None
    unit: str | None = None
    color_limits: tuple[float, float] | None = None
    color_map: str = "scalar"
    color_norm: str = "auto"
    background_color: Any = "white"
    max_refresh_hz: float | None = None
    camera_orbit_sensitivity: float = DEFAULT_MORPHOLOGY_CAMERA_ORBIT_SENSITIVITY
    camera_pan_sensitivity: float = DEFAULT_MORPHOLOGY_CAMERA_PAN_SENSITIVITY
    camera_zoom_sensitivity: float = DEFAULT_MORPHOLOGY_CAMERA_ZOOM_SENSITIVITY
    selected: Any = None
    selectable: bool = True
    select_multiple: bool = False
    panel: bool = True

    def declare(self, context) -> MorphologyRef:
        if not isinstance(self.geometry, (MorphologyGeometry, GeometryRef)):
            raise TypeError(
                "morphology expects MorphologyGeometry or GeometryRef geometry"
            )
        if self.select_multiple and not self.selectable:
            raise ValueError(
                "morphology(select_multiple=True) requires selectable=True"
            )
        authored_color_inputs = sum(
            value is not None
            for value in (self.color, self.values, self.read)
        )
        if authored_color_inputs > 1:
            raise ValueError(
                "morphology accepts color=..., values=..., or read=..., not more than one"
            )

        if isinstance(self.geometry, MorphologyGeometry):
            spec = self.geometry.to_spec()
            geometry = context.geometry(
                spec.kind,
                self.name,
                data=spec.data,
                metadata=spec.metadata,
            )
        else:
            geometry = self.geometry
        color = self.color
        if self.values is not None or self.read is not None:
            if not isinstance(self.geometry, MorphologyGeometry):
                raise ValueError(
                    "morphology values=/read= requires MorphologyGeometry so "
                    "entity labels are known; use color=DataRef with GeometryRef"
                )
            if self.read is not None:
                color = context.data(
                    f"{self.name} values",
                    read=self.read,
                    labels=self.geometry.entity_ids,
                    unit=self.unit,
                )
            else:
                color = context.data(
                    f"{self.name} values",
                    values=self.values,
                    labels=self.geometry.entity_ids,
                    unit=self.unit,
                )

        panel_ref, selection = _declare_morphology_view(
            context,
            name=self.name,
            geometry=geometry,
            color=color,
            selection_initial=self.selected,
            selection_multiple=self.select_multiple,
            selectable=self.selectable,
            panel=self.panel,
            color_map=self.color_map,
            color_limits=self.color_limits,
            color_norm=self.color_norm,
            background_color=self.background_color,
            max_refresh_hz=self.max_refresh_hz,
            camera_orbit_sensitivity=self.camera_orbit_sensitivity,
            camera_pan_sensitivity=self.camera_pan_sensitivity,
            camera_zoom_sensitivity=self.camera_zoom_sensitivity,
        )
        return MorphologyRef(
            id=panel_ref.id,
            selected=selection,
        )


__all__ = [
    "DEFAULT_MORPHOLOGY_CAMERA_ORBIT_SENSITIVITY",
    "DEFAULT_MORPHOLOGY_CAMERA_PAN_SENSITIVITY",
    "DEFAULT_MORPHOLOGY_CAMERA_ZOOM_SENSITIVITY",
    "Morphology",
]
