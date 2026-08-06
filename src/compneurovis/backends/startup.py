"""Simulator-owned data available before source widgets are compiled."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from compneurovis.core.app_spec import (
    AppSpec,
    DataCatalog,
    InteractionCatalog,
    LayoutCatalog,
    LayoutSpec,
    ViewCatalog,
)
from compneurovis.core.field import FieldSpec
from compneurovis.core.geometry import GeometrySpec


@dataclass(frozen=True, slots=True)
class StartupData:
    """Neutral simulator data handed to the source-level compiler."""

    fields: tuple[FieldSpec, ...] = ()
    geometries: tuple[GeometrySpec, ...] = ()
    title: str = "CompNeuroVis"
    metadata: Mapping[str, Any] | None = None

    def app_spec(self) -> AppSpec:
        return AppSpec(
            data=DataCatalog(
                fields={field.id: field for field in self.fields},
                geometries={geometry.id: geometry for geometry in self.geometries},
            ),
            view_catalog=ViewCatalog(),
            interactions=InteractionCatalog(),
            layout_catalog=LayoutCatalog.single(LayoutSpec(title=self.title)),
            metadata={} if self.metadata is None else dict(self.metadata),
        )


__all__ = ["StartupData"]
