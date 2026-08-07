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
    """Language-neutral canonical geometry declaration."""

    kind: str = ""
    data: Mapping[str, Any] = field(default_factory=FrozenDict)
    metadata: Mapping[str, Any] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        kind = str(self.kind).strip()
        if not kind:
            raise ValueError("GeometrySpec.kind cannot be empty")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self,
            "data",
            freeze_spec_data(self.data, path="GeometrySpec.data"),
        )
        object.__setattr__(
            self,
            "metadata",
            freeze_spec_data(self.metadata, path="GeometrySpec.metadata"),
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


def _entity_value(values: Any, *, index: int, entity_count: int) -> Any:
    if isinstance(values, (str, bytes, Mapping)):
        return _NOT_ENTITY_SCALAR
    try:
        if len(values) != entity_count:
            return _NOT_ENTITY_SCALAR
        value = values[index]
    except (IndexError, TypeError):
        return _NOT_ENTITY_SCALAR
    return _entity_scalar(value)


def geometry_entity_info(
    spec: GeometrySpec,
    entity_id: str,
) -> dict[str, Any] | None:
    """Resolve neutral metadata for one entity in any geometry.

    `entity_ids` establishes identity. Any scalar-per-entity array in `data` is
    exposed under its authored key, and `metadata["entities"]` may provide
    explicit per-id mappings. No geometry kind receives a special reconstruction
    path.
    """
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
        if name == "entity_ids":
            continue
        scalar = _entity_value(
            values,
            index=index,
            entity_count=len(entity_ids),
        )
        if scalar is not _NOT_ENTITY_SCALAR:
            info[str(name)] = scalar

    aliases = spec.metadata.get("entity_fields")
    if isinstance(aliases, Mapping):
        for field_name, data_name in aliases.items():
            values = spec.data.get(str(data_name))
            scalar = _entity_value(
                values,
                index=index,
                entity_count=len(entity_ids),
            )
            if scalar is not _NOT_ENTITY_SCALAR:
                info[str(field_name)] = scalar

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

    def entity_info(
        self,
        entity_id: str,
        *,
        geometry_id: str | None = None,
    ) -> dict[str, Any]:
        candidates = (
            self.specs
            if geometry_id is None
            else tuple(
                spec for spec in self.specs if spec.id == str(geometry_id)
            )
        )
        for spec in candidates:
            info = geometry_entity_info(spec, entity_id)
            if info is not None:
                return info
        suffix = (
            ""
            if geometry_id is None
            else f" in geometry {geometry_id!r}"
        )
        raise KeyError(f"Unknown geometry entity id {entity_id!r}{suffix}")


__all__ = [
    "GeometrySpec",
    "GeometryEntityLookup",
    "geometry_entity_info",
]
