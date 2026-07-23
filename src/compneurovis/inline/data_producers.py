"""Generic callable-backed data producers used by source widgets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from compneurovis.core.field import FieldSpec
from compneurovis.core.messages import FieldReplace


@dataclass
class ArrayFieldBinding:
    """One-dimensional static or callable-backed data producer."""

    field_id: str
    dim: str
    labels: tuple[str, ...]
    values: Any = None
    read: Callable[[], Any] | None = None
    unit: str | None = None

    def resolve(self) -> np.ndarray:
        raw = self.read() if self.read is not None else self.values
        array = np.asarray(raw, dtype=np.float32).reshape(-1)
        if array.size != len(self.labels):
            raise ValueError(
                f"data {self.field_id!r} expects {len(self.labels)} values "
                f"over dimension {self.dim!r}, got {array.size}"
            )
        return array

    def field_spec(self) -> FieldSpec:
        return FieldSpec(
            id=self.field_id,
            initial_values=self.resolve(),
            dims=(self.dim,),
            coords={self.dim: np.asarray(self.labels)},
            unit=self.unit,
        )

    def replace_payload(self) -> FieldReplace:
        return FieldReplace(field_id=self.field_id, values=self.resolve())


@dataclass
class DerivedValueBinding:
    """Callable-backed runtime value with an independent refresh cadence."""

    name: str
    fn: Callable[[], Any]
    max_refresh_hz: float | None = 10.0
    initial: Any = None
    _last_eval_s: float = field(init=False, default=float("-inf"))

    def due(self, now: float) -> bool:
        interval = (
            1.0 / self.max_refresh_hz
            if self.max_refresh_hz and self.max_refresh_hz > 0
            else 0.0
        )
        return (now - self._last_eval_s) >= interval

    def evaluate(self, now: float) -> Any:
        self._last_eval_s = now
        return self.fn()


__all__ = ["ArrayFieldBinding", "DerivedValueBinding"]
