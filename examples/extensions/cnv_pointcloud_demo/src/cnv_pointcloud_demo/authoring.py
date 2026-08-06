from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np

from compneurovis import PANEL_KIND_VIEW_3D
from compneurovis.widgets import DataRef, GeometryRef, PanelRef, Widget

GEOMETRY_KIND = "point_cloud"
VIEW_KIND = "point_cloud_3d"


@dataclass(frozen=True, slots=True)
class PointCloudRef(PanelRef):
    """Typed references exposed by one authored point-cloud instance."""

    geometry: GeometryRef
    values: DataRef


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
        panel = context.view(
            VIEW_KIND,
            self.name,
            inputs={"values": values},
            geometries={"points": geometry},
            properties=dict(self.style),
            panel_kind=PANEL_KIND_VIEW_3D,
        )
        return PointCloudRef(
            id=panel.id,
            geometry=geometry,
            values=values,
        )


__all__ = [
    "GEOMETRY_KIND",
    "PointCloud3D",
    "PointCloudRef",
    "VIEW_KIND",
]
