"""Stable public names for NEURON sections owned by CompNeuroVis importers."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


IMPORTED_CELL_OWNER_NAME = "compneurovis_imported_cell"
_IMPORTED_CELL_PREFIX = f"{IMPORTED_CELL_OWNER_NAME}."


def public_section_name(name: str) -> str:
    """Remove only CompNeuroVis's internal Import3d owner prefix."""
    value = str(name)
    if value.startswith(_IMPORTED_CELL_PREFIX):
        return value[len(_IMPORTED_CELL_PREFIX):]
    return value


def section_lookup(sections: Iterable[Any]) -> dict[str, Any]:
    """Index sections by stable public name, rejecting ambiguous models."""
    result: dict[str, Any] = {}
    for section in sections:
        name = public_section_name(section.name())
        if name in result:
            raise ValueError(
                f"NEURON model contains duplicate public section name {name!r}"
            )
        result[name] = section
    return result


__all__ = [
    "IMPORTED_CELL_OWNER_NAME",
    "public_section_name",
    "section_lookup",
]
