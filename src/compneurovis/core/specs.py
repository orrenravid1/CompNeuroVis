from __future__ import annotations

from dataclasses import dataclass


class SpecBase:
    """Marker for immutable declarative blueprint values."""


@dataclass(frozen=True, slots=True)
class IdentifiedSpec(SpecBase):
    """Base for immutable specs addressed by a stable id."""

    id: str


__all__ = ["IdentifiedSpec", "SpecBase"]
