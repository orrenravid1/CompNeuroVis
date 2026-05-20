from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar

import numpy as np


@dataclass(frozen=True, slots=True)
class GeometrySpec:
    id: str


@dataclass(frozen=True, slots=True)
class MorphologyGeometrySpec(GeometrySpec):
    kind: ClassVar[str] = "morphology"

    positions: np.ndarray
    orientations: np.ndarray
    radii: np.ndarray
    lengths: np.ndarray
    entity_ids: tuple[str, ...]
    section_names: tuple[str, ...]
    xlocs: np.ndarray
    colors: np.ndarray | None = None
    labels: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        positions = np.asarray(self.positions, dtype=np.float32)
        orientations = np.asarray(self.orientations, dtype=np.float32)
        radii = np.asarray(self.radii, dtype=np.float32)
        lengths = np.asarray(self.lengths, dtype=np.float32)
        xlocs = np.asarray(self.xlocs, dtype=np.float32)
        colors = None if self.colors is None else np.asarray(self.colors, dtype=np.float32)
        n = positions.shape[0]

        if positions.shape != (n, 3):
            raise ValueError("MorphologyGeometrySpec positions must have shape (n, 3)")
        if orientations.shape != (n, 3, 3):
            raise ValueError("MorphologyGeometrySpec orientations must have shape (n, 3, 3)")
        if radii.shape != (n,) or lengths.shape != (n,) or xlocs.shape != (n,):
            raise ValueError("MorphologyGeometrySpec radii, lengths, and xlocs must have shape (n,)")
        if len(self.entity_ids) != n or len(self.section_names) != n:
            raise ValueError("MorphologyGeometrySpec entity_ids and section_names must match segment count")
        if colors is not None and colors.shape != (n, 4):
            raise ValueError("MorphologyGeometrySpec colors must have shape (n, 4)")
        if self.labels and len(self.labels) != n:
            raise ValueError("MorphologyGeometrySpec labels must match segment count")

        object.__setattr__(self, "positions", positions)
        object.__setattr__(self, "orientations", orientations)
        object.__setattr__(self, "radii", radii)
        object.__setattr__(self, "lengths", lengths)
        object.__setattr__(self, "xlocs", xlocs)
        object.__setattr__(self, "colors", colors)
        object.__setattr__(self, "entity_ids", tuple(self.entity_ids))
        object.__setattr__(self, "section_names", tuple(self.section_names))
        object.__setattr__(self, "labels", tuple(self.labels) if self.labels else tuple(self.entity_ids))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def entity_index(self, entity_id: str) -> int:
        try:
            return self.entity_ids.index(entity_id)
        except ValueError as exc:
            raise KeyError(f"Unknown morphology entity id '{entity_id}'") from exc

    def label_for(self, entity_id: str) -> str:
        return self.labels[self.entity_index(entity_id)]

    def entity_info(self, entity_id: str) -> dict[str, Any]:
        idx = self.entity_index(str(entity_id))
        return {
            "index": idx,
            "entity_id": self.entity_ids[idx],
            "section_name": self.section_names[idx],
            "xloc": float(self.xlocs[idx]),
            "label": self.labels[idx],
        }


@dataclass(frozen=True, slots=True)
class GridGeometrySpec(GeometrySpec):
    kind: ClassVar[str] = "grid"

    dims: tuple[str, str]
    coords: dict[str, np.ndarray]
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        dims = tuple(self.dims)
        if len(dims) != 2:
            raise ValueError("GridGeometrySpec requires exactly two dims")
        coords = {str(name): np.asarray(value) for name, value in self.coords.items()}
        if set(coords.keys()) != set(dims):
            raise ValueError("GridGeometrySpec coord keys must exactly match dims")
        for dim in dims:
            if coords[dim].ndim != 1:
                raise ValueError("GridGeometrySpec coords must be one-dimensional")
        object.__setattr__(self, "dims", dims)
        object.__setattr__(self, "coords", coords)
        object.__setattr__(self, "metadata", dict(self.metadata))
