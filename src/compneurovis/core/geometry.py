from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from compneurovis.core._immutability import (
    FrozenDict,
    freeze_spec_data,
)
from compneurovis.core.specs import IdentifiedSpec


@dataclass(frozen=True, slots=True)
class GeometrySpec(IdentifiedSpec):
    pass


@dataclass(frozen=True, slots=True)
class ExtensionGeometrySpec(GeometrySpec):
    """Language-neutral geometry declared by a registered widget kind."""

    kind: str = ""
    data: Mapping[str, Any] = field(default_factory=FrozenDict)
    metadata: Mapping[str, Any] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        kind = str(self.kind).strip()
        if not kind:
            raise ValueError("ExtensionGeometrySpec.kind cannot be empty")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self,
            "data",
            freeze_spec_data(self.data, path="ExtensionGeometrySpec.data"),
        )
        object.__setattr__(
            self,
            "metadata",
            freeze_spec_data(self.metadata, path="ExtensionGeometrySpec.metadata"),
        )


__all__ = [
    "ExtensionGeometrySpec",
    "GeometrySpec",
]
