from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from compneurovis.core._immutability import FrozenDict
from compneurovis.core.specs import SpecBase


DEFAULT_FRAGMENT_ID = "main"


@dataclass(frozen=True, slots=True)
class AppRef(SpecBase):
    """Reference to an object inside one app fragment."""

    id: str
    fragment_id: str = DEFAULT_FRAGMENT_ID

    def __post_init__(self) -> None:
        fragment_id = str(self.fragment_id or DEFAULT_FRAGMENT_ID)
        local_id = str(self.id)
        if not fragment_id.strip():
            raise ValueError("AppRef.fragment_id cannot be empty")
        if not local_id.strip():
            raise ValueError("AppRef.id cannot be empty")
        if ":" in fragment_id or ":" in local_id:
            raise ValueError(
                "AppRef values cannot contain ':'. Construct scoped references as "
                "AppRef(id='field', fragment_id='source')."
            )
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
    if isinstance(value, AppRef):
        return value
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
            frozen[normalized_role] = value
            continue
        normalized_value = str(value).strip()
        if not normalized_value:
            raise ValueError(f"{path} source ids cannot be empty")
        frozen[normalized_role] = normalized_value
    return FrozenDict(frozen)


__all__ = ["AppRef", "DEFAULT_FRAGMENT_ID", "app_ref"]
