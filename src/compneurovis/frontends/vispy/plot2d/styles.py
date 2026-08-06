"""Immutable per-series style normalization and lookup."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from compneurovis.core._immutability import FrozenDict


def freeze_series_style(value: Any) -> Any:
    if isinstance(value, Mapping):
        return FrozenDict(value)
    return tuple(value)


def series_style(container: Any, label: str, index: int, default: Any) -> Any:
    if isinstance(container, Mapping):
        return container.get(label, default)
    if container:
        return container[index % len(container)]
    return default


__all__ = ["freeze_series_style", "series_style"]
