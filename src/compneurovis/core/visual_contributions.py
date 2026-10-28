"""Neutral visual content contributed into a capable target panel."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from compneurovis.core._immutability import FrozenDict
from compneurovis.core.references import AppRef, freeze_ref_map
from compneurovis.core.specs import IdentifiedSpec
from compneurovis.core.values import freeze_binding_data


@dataclass(frozen=True, slots=True)
class VisualContributionSpec(IdentifiedSpec):
    """Language-neutral layer declaration rendered by a target capability."""

    kind: str
    capability: str
    inputs: Mapping[str, str | AppRef] = field(default_factory=FrozenDict)
    geometries: Mapping[str, str | AppRef] = field(default_factory=FrozenDict)
    hit_targets: Mapping[str, str | AppRef] = field(default_factory=FrozenDict)
    selections: Mapping[str, str | AppRef] = field(default_factory=FrozenDict)
    properties: Mapping[str, Any] = field(default_factory=FrozenDict)
    max_refresh_hz: float | None = None

    def __post_init__(self) -> None:
        kind = str(self.kind).strip()
        capability = str(self.capability).strip()
        if not kind:
            raise ValueError("VisualContributionSpec.kind cannot be empty")
        if not capability:
            raise ValueError("VisualContributionSpec.capability cannot be empty")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "capability", capability)
        object.__setattr__(
            self,
            "inputs",
            freeze_ref_map(self.inputs, path="VisualContributionSpec.inputs"),
        )
        object.__setattr__(
            self,
            "geometries",
            freeze_ref_map(
                self.geometries, path="VisualContributionSpec.geometries"
            ),
        )
        object.__setattr__(
            self,
            "hit_targets",
            freeze_ref_map(
                self.hit_targets, path="VisualContributionSpec.hit_targets"
            ),
        )
        object.__setattr__(
            self,
            "selections",
            freeze_ref_map(
                self.selections, path="VisualContributionSpec.selections"
            ),
        )
        object.__setattr__(
            self,
            "properties",
            freeze_binding_data(
                self.properties, path="VisualContributionSpec.properties"
            ),
        )


__all__ = ["VisualContributionSpec"]
