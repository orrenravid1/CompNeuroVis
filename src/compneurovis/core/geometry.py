from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

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


_NOT_ENTITY_SCALAR = object()


def _entity_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (str, bytes, bool, int, float)):
        return value
    item = getattr(value, "item", None)
    if callable(item):
        try:
            scalar = item()
        except ValueError:
            return _NOT_ENTITY_SCALAR
        if scalar is None or isinstance(
            scalar, (str, bytes, bool, int, float)
        ):
            return scalar
    return _NOT_ENTITY_SCALAR


def geometry_entity_info(
    spec: GeometrySpec,
    entity_id: str,
) -> dict[str, Any] | None:
    """Resolve neutral metadata for one entity in any extension geometry.

    `entity_ids` establishes identity. Any scalar-per-entity array in `data` is
    exposed under its authored key, and `metadata["entities"]` may provide
    explicit per-id mappings. No geometry kind receives a special reconstruction
    path.
    """
    if not isinstance(spec, ExtensionGeometrySpec):
        return None
    raw_ids = spec.data.get("entity_ids")
    if raw_ids is None:
        return None
    entity_ids = tuple(str(value) for value in raw_ids)
    resolved_id = str(entity_id)
    try:
        index = entity_ids.index(resolved_id)
    except ValueError:
        return None

    info: dict[str, Any] = {"index": index, "entity_id": resolved_id}
    for name, values in spec.data.items():
        if name == "entity_ids" or isinstance(values, (str, bytes, Mapping)):
            continue
        try:
            if len(values) != len(entity_ids):
                continue
            value = values[index]
        except (IndexError, TypeError):
            continue
        scalar = _entity_scalar(value)
        if scalar is not _NOT_ENTITY_SCALAR:
            info[str(name)] = scalar

    explicit = spec.metadata.get("entities")
    if isinstance(explicit, Mapping):
        details = explicit.get(resolved_id)
        if isinstance(details, Mapping):
            info.update(details)
    return info


class GeometryEntityLookup:
    """Entity metadata lookup over an arbitrary neutral geometry catalog."""

    def __init__(self, specs: Iterable[GeometrySpec]) -> None:
        self.specs = tuple(specs)

    def entity_info(self, entity_id: str) -> dict[str, Any]:
        for spec in self.specs:
            info = geometry_entity_info(spec, entity_id)
            if info is not None:
                return info
        raise KeyError(f"Unknown geometry entity id {entity_id!r}")


__all__ = [
    "ExtensionGeometrySpec",
    "GeometryEntityLookup",
    "GeometrySpec",
    "geometry_entity_info",
]
