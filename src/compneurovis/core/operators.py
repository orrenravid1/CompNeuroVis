from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from compneurovis.core._immutability import FrozenDict, freeze_spec_data
from compneurovis.core.references import AppRef, freeze_ref_map
from compneurovis.core.specs import IdentifiedSpec
from compneurovis.core.values import ValueBindingSpec


@dataclass(frozen=True, slots=True)
class OperatorSpec(IdentifiedSpec):
    pass


@dataclass(frozen=True, slots=True)
class ExtensionOperatorSpec(OperatorSpec):
    """Language-neutral data operator selected through a registered kind."""

    kind: str = ""
    inputs: Mapping[str, str | AppRef] = field(default_factory=FrozenDict)
    geometries: Mapping[str, str | AppRef] = field(default_factory=FrozenDict)
    properties: Mapping[str, Any] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        kind = str(self.kind).strip()
        if not kind:
            raise ValueError("ExtensionOperatorSpec.kind cannot be empty")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self,
            "inputs",
            freeze_ref_map(self.inputs, path="ExtensionOperatorSpec.inputs"),
        )
        object.__setattr__(
            self,
            "geometries",
            freeze_ref_map(
                self.geometries,
                path="ExtensionOperatorSpec.geometries",
            ),
        )
        object.__setattr__(
            self,
            "properties",
            _freeze_operator_data(
                self.properties,
                path="ExtensionOperatorSpec.properties",
            ),
        )


def _freeze_operator_data(value: Any, *, path: str) -> Any:
    if isinstance(value, ValueBindingSpec):
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise TypeError(f"{path} keys must be non-empty strings")
            frozen[key] = _freeze_operator_data(item, path=f"{path}.{key}")
        return FrozenDict(frozen)
    if isinstance(value, (tuple, list)):
        return tuple(
            _freeze_operator_data(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    return freeze_spec_data(value, path=path)


__all__ = ["ExtensionOperatorSpec", "OperatorSpec"]
