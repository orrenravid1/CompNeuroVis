from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np

from compneurovis.widgets import (
    DataRef,
    GeometryRef,
    PanelRef,
    SelectionRef,
    Widget,
)

GEOMETRY_KIND = "point_cloud"
VIEW_KIND = "point_cloud_3d"
SCATTER_VIEW_KIND = "scatter_2d"


@dataclass(frozen=True, slots=True)
class PointCloudRef(PanelRef):
    """Typed references exposed by one authored point-cloud instance."""

    geometry: GeometryRef
    values: DataRef
    selected: SelectionRef | None


@dataclass(frozen=True, slots=True)
class PointCloud3D(Widget[PointCloudRef]):
    """Static or callable-backed 3-D point cloud authored through public APIs."""

    name: str
    positions: Any
    values: Any = None
    read: Callable[[], Any] | None = None
    entity_ids: Sequence[str] | None = None
    labels: Sequence[str] | None = None
    unit: str | None = None
    selected: Any = None
    selectable: bool = True
    select_multiple: bool = False
    style: dict[str, Any] = field(default_factory=dict)

    def declare(self, context) -> PointCloudRef:
        positions = np.asarray(self.positions, dtype=np.float32)
        if positions.ndim != 2 or positions.shape[1] != 3:
            raise ValueError("PointCloud3D positions must have shape (n, 3)")
        count = positions.shape[0]
        entity_ids = (
            tuple(str(value) for value in self.entity_ids)
            if self.entity_ids is not None
            else tuple(str(index) for index in range(count))
        )
        labels = (
            tuple(str(value) for value in self.labels)
            if self.labels is not None
            else entity_ids
        )
        if len(entity_ids) != count or len(labels) != count:
            raise ValueError(
                "PointCloud3D entity_ids and labels must match the point count"
            )
        if self.values is not None and self.read is not None:
            raise ValueError("PointCloud3D accepts values=... or read=..., not both")
        if self.select_multiple and not self.selectable:
            raise ValueError(
                "PointCloud3D(select_multiple=True) requires selectable=True"
            )

        geometry = context.geometry(
            GEOMETRY_KIND,
            f"{self.name} geometry",
            data={
                "positions": positions,
                "entity_ids": entity_ids,
                "labels": labels,
            },
        )
        if self.read is None:
            initial_values = (
                np.zeros(count, dtype=np.float32)
                if self.values is None
                else self.values
            )
            values = context.data(
                f"{self.name} values",
                values=initial_values,
                labels=entity_ids,
                unit=self.unit,
            )
        else:
            values = context.data(
                f"{self.name} values",
                read=self.read,
                labels=entity_ids,
                unit=self.unit,
            )
        selection = (
            context.selection(
                f"{self.name} entities",
                geometry=geometry,
                initial=self.selected,
                multiple=self.select_multiple,
            )
            if self.selectable
            else None
        )
        panel = context.view(
            VIEW_KIND,
            self.name,
            inputs={"values": values},
            geometries={"points": geometry},
            selections=({"entities": selection} if selection is not None else {}),
            properties=dict(self.style),
            panel_kind="scene_3d",
        )
        return PointCloudRef(
            id=panel.id,
            geometry=geometry,
            values=values,
            selected=selection,
        )


@dataclass(frozen=True, slots=True)
class PointCloudPlaneSlice(Widget[DataRef]):
    """Finite axis-aligned slab over a point cloud, producing projected data."""

    name: str
    source: PointCloudRef
    axis: Any = "z"
    position: Any = 0.5
    thickness: Any = 0.15
    overlay: dict[str, Any] | None = None

    def declare(self, context) -> DataRef:
        from cnv_pointcloud_demo.slice_operator import SLICE_OPERATOR_KIND

        return context.operator(
            SLICE_OPERATOR_KIND,
            self.name,
            inputs={"values": self.source.values},
            geometries={"points": self.source.geometry},
            properties={
                "axis": self.axis,
                "position": self.position,
                "thickness": self.thickness,
                **({} if self.overlay is None else dict(self.overlay)),
            },
            contributes_to=(self.source,),
        )


@dataclass(frozen=True, slots=True)
class Scatter2D(Widget[PanelRef]):
    """Independent 2-D scatter consumer for projected point data."""

    name: str
    source: DataRef
    style: dict[str, Any] = field(default_factory=dict)

    def declare(self, context) -> PanelRef:
        return context.view(
            SCATTER_VIEW_KIND,
            self.name,
            inputs={"data": self.source},
            properties=dict(self.style),
        )


__all__ = [
    "GEOMETRY_KIND",
    "PointCloud3D",
    "PointCloudPlaneSlice",
    "PointCloudRef",
    "SCATTER_VIEW_KIND",
    "Scatter2D",
    "VIEW_KIND",
]
