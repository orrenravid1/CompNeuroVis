from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from compneurovis.core._immutability import FrozenDict
from compneurovis.core.specs import SpecBase


DEFAULT_FRAGMENT_ID = "main"


def validate_local_id(value: object, *, path: str) -> str:
    """Validate one unqualified id used inside an app fragment."""

    if not isinstance(value, str):
        raise TypeError(f"{path} must be a string")
    normalized = str(value)
    if not normalized.strip():
        raise ValueError(f"{path} cannot be empty")
    if normalized != normalized.strip():
        raise ValueError(f"{path} cannot contain surrounding whitespace")
    if ":" in normalized:
        raise ValueError(
            f"{path} cannot contain ':'; use AppRef(id=..., fragment_id=...) "
            "for scoped references"
        )
    return normalized


@dataclass(frozen=True, slots=True)
class AppRef(SpecBase):
    """Reference to an object inside one app fragment."""

    id: str
    fragment_id: str = DEFAULT_FRAGMENT_ID

    def __post_init__(self) -> None:
        fragment_id = validate_local_id(
            self.fragment_id or DEFAULT_FRAGMENT_ID,
            path="AppRef.fragment_id",
        )
        local_id = validate_local_id(self.id, path="AppRef.id")
        object.__setattr__(self, "fragment_id", fragment_id)
        object.__setattr__(self, "id", local_id)

    def flat_id(self) -> str:
        if self.fragment_id == DEFAULT_FRAGMENT_ID:
            return self.id
        return f"{self.fragment_id}:{self.id}"

    def __str__(self) -> str:
        return self.flat_id()


def app_ref(
    value: str | AppRef,
    *,
    fragment_id: str = DEFAULT_FRAGMENT_ID,
) -> AppRef:
    """Resolve a local id or preserve an explicitly scoped reference."""
    if type(value) is AppRef:
        return value
    if isinstance(value, AppRef):
        return AppRef(id=value.id, fragment_id=value.fragment_id)
    return AppRef(str(value), fragment_id=fragment_id)


def freeze_ref_map(
    values: Mapping[str, str | AppRef],
    *,
    path: str,
) -> FrozenDict[str, str | AppRef]:
    """Validate named canonical references without erasing fragment scope."""
    frozen: dict[str, str | AppRef] = {}
    for role, value in values.items():
        normalized_role = str(role).strip()
        if not normalized_role:
            raise ValueError(f"{path} roles cannot be empty")
        if isinstance(value, AppRef):
            frozen[normalized_role] = app_ref(value)
            continue
        normalized_value = validate_local_id(
            value,
            path=f"{path}[{normalized_role!r}]",
        )
        frozen[normalized_role] = normalized_value
    return FrozenDict(frozen)


__all__ = ["AppRef", "DEFAULT_FRAGMENT_ID", "app_ref", "validate_local_id"]
