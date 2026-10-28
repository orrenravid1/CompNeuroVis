from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from compneurovis.core._immutability import FrozenDict
from compneurovis.core.references import AppRef, freeze_ref_map
from compneurovis.core.specs import IdentifiedSpec
from compneurovis.core.values import freeze_binding_data


@dataclass(frozen=True, slots=True)
class OperatorSpec(IdentifiedSpec):
    """Language-neutral canonical data-operator declaration."""

    kind: str = ""
    inputs: Mapping[str, str | AppRef] = field(default_factory=FrozenDict)
    geometries: Mapping[str, str | AppRef] = field(default_factory=FrozenDict)
    properties: Mapping[str, Any] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        kind = str(self.kind).strip()
        if not kind:
            raise ValueError("OperatorSpec.kind cannot be empty")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self,
            "inputs",
            freeze_ref_map(self.inputs, path="OperatorSpec.inputs"),
        )
        object.__setattr__(
            self,
            "geometries",
            freeze_ref_map(
                self.geometries,
                path="OperatorSpec.geometries",
            ),
        )
        object.__setattr__(
            self,
            "properties",
            freeze_binding_data(
                self.properties,
                path="OperatorSpec.properties",
            ),
        )


__all__ = ["OperatorSpec"]
