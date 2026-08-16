"""Frontend-neutral morphology geometry shared by authoring and simulators."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import numpy as np

from compneurovis.core._immutability import (
    FrozenDict,
    freeze_spec_data,
    readonly_array,
)
from compneurovis.core.geometry import GeometrySpec


MORPHOLOGY_GEOMETRY_KIND = "morphology"


@dataclass(frozen=True, slots=True)
class MorphologyGeometry:
    """Python authoring/runtime form of morphology geometry.

    Canonical app specs carry only an :class:`GeometrySpec`. The
    built-in widget and renderer reconstruct this typed form at their own
    boundaries, so no morphology-specific class is privileged in core.
    """

    id: str
    positions: np.ndarray
    orientations: np.ndarray
    radii: np.ndarray
    lengths: np.ndarray
    entity_ids: tuple[str, ...]
    section_names: tuple[str, ...]
    xlocs: np.ndarray
    colors: np.ndarray | None = None
    labels: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        positions = readonly_array(self.positions, dtype=np.float32)
        orientations = readonly_array(self.orientations, dtype=np.float32)
        radii = readonly_array(self.radii, dtype=np.float32)
        lengths = readonly_array(self.lengths, dtype=np.float32)
        xlocs = readonly_array(self.xlocs, dtype=np.float32)
        colors = (
            None
            if self.colors is None
            else readonly_array(self.colors, dtype=np.float32)
        )
        n = positions.shape[0]
        if positions.shape != (n, 3):
            raise ValueError("MorphologyGeometry positions must have shape (n, 3)")
        if orientations.shape != (n, 3, 3):
            raise ValueError("MorphologyGeometry orientations must have shape (n, 3, 3)")
        if radii.shape != (n,) or lengths.shape != (n,) or xlocs.shape != (n,):
            raise ValueError(
                "MorphologyGeometry radii, lengths, and xlocs must have shape (n,)"
            )
        if len(self.entity_ids) != n or len(self.section_names) != n:
            raise ValueError(
                "MorphologyGeometry entity_ids and section_names must match segment count"
            )
        if colors is not None and colors.shape != (n, 4):
            raise ValueError("MorphologyGeometry colors must have shape (n, 4)")
        if self.labels and len(self.labels) != n:
            raise ValueError("MorphologyGeometry labels must match segment count")
        object.__setattr__(self, "positions", positions)
        object.__setattr__(self, "orientations", orientations)
        object.__setattr__(self, "radii", radii)
        object.__setattr__(self, "lengths", lengths)
        object.__setattr__(self, "xlocs", xlocs)
        object.__setattr__(self, "colors", colors)
        object.__setattr__(self, "entity_ids", tuple(self.entity_ids))
        object.__setattr__(self, "section_names", tuple(self.section_names))
        object.__setattr__(
            self,
            "labels",
            tuple(self.labels) if self.labels else tuple(self.entity_ids),
        )
        object.__setattr__(
            self,
            "metadata",
            freeze_spec_data(
                self.metadata,
                path=f"MorphologyGeometry[{self.id!r}].metadata",
            ),
        )

    def spec_data(self) -> dict[str, Any]:
        """Return the language-neutral payload placed in canonical AppSpec."""
        return {
            "positions": self.positions,
            "orientations": self.orientations,
            "radii": self.radii,
            "lengths": self.lengths,
            "entity_ids": self.entity_ids,
            "section_names": self.section_names,
            "xlocs": self.xlocs,
            "colors": self.colors,
            "labels": self.labels,
        }

    def to_spec(self) -> GeometrySpec:
        metadata = dict(self.metadata)
        entity_fields = {
            "position": "positions",
            "orientation": "orientations",
            "radius": "radii",
            "length": "lengths",
            "section_name": "section_names",
            "xloc": "xlocs",
            "label": "labels",
        }
        existing_entity_fields = metadata.get("entity_fields")
        if isinstance(existing_entity_fields, Mapping):
            entity_fields.update(
                {
                    str(field_name): str(data_name)
                    for field_name, data_name in existing_entity_fields.items()
                }
            )
        metadata["entity_fields"] = entity_fields
        return GeometrySpec(
            id=self.id,
            kind=MORPHOLOGY_GEOMETRY_KIND,
            data=self.spec_data(),
            metadata=metadata,
        )

    def entity_index(self, entity_id: str) -> int:
        try:
            return self.entity_ids.index(entity_id)
        except ValueError as exc:
            raise KeyError(f"Unknown morphology entity id {entity_id!r}") from exc

    def entity_info(self, entity_id: str) -> dict[str, Any]:
        index = self.entity_index(str(entity_id))
        return {
            "index": index,
            "entity_id": self.entity_ids[index],
            "position": tuple(float(value) for value in self.positions[index]),
            "orientation": tuple(
                tuple(float(value) for value in row)
                for row in self.orientations[index]
            ),
            "radius": float(self.radii[index]),
            "length": float(self.lengths[index]),
            "section_name": self.section_names[index],
            "xloc": float(self.xlocs[index]),
            "label": self.labels[index],
        }


def morphology_geometry_from_spec(
    spec: GeometrySpec,
) -> MorphologyGeometry | None:
    """Reconstruct the built-in type from a neutral morphology geometry spec."""
    if not isinstance(spec, GeometrySpec):
        return None
    if spec.kind != MORPHOLOGY_GEOMETRY_KIND:
        return None
    data = spec.data
    try:
        return MorphologyGeometry(
            id=spec.id,
            positions=data["positions"],
            orientations=data["orientations"],
            radii=data["radii"],
            lengths=data["lengths"],
            entity_ids=tuple(data["entity_ids"]),
            section_names=tuple(data["section_names"]),
            xlocs=data["xlocs"],
            colors=data.get("colors"),
            labels=tuple(data.get("labels", ())),
            metadata=spec.metadata,
        )
    except KeyError as exc:
        raise ValueError(
            f"Morphology geometry {spec.id!r} is missing data key {exc.args[0]!r}"
        ) from exc


__all__ = [
    "MORPHOLOGY_GEOMETRY_KIND",
    "MorphologyGeometry",
    "morphology_geometry_from_spec",
]
