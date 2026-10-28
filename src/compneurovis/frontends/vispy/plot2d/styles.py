"""Immutable per-series style normalization and lookup."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from compneurovis.core.values import freeze_binding_data


def freeze_series_style(value: Any) -> Any:
    return freeze_binding_data(value, path="series_style")


def series_style(container: Any, label: str, index: int, default: Any) -> Any:
    if isinstance(container, Mapping):
        return container.get(label, default)
    if container:
        return container[index % len(container)]
    return default


__all__ = ["freeze_series_style", "series_style"]
