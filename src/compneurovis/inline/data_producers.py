"""Generic callable-backed data producers used by source widgets."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Callable, TypeAlias

import numpy as np

from compneurovis.core.field import FieldSpec
from compneurovis.core.messages import FieldAppend, FieldReplace, update_message
from compneurovis.inline._ids import slug


SeriesReaders: TypeAlias = Callable[[], float] | Mapping[str, Callable[[], float]]


@dataclass
class SnapshotProducer:
    """Static or callable-backed producer for an N-dimensional field.

    Emits a whole-field ``FieldReplace`` (snapshot semantics). Rank and coord
    dtype are parameters, not distinct types: a 1-D categorical field (string
    coords) and a 2-D surface (float coords) are the same producer at different
    ``dims`` / ``coords``. Nothing here branches on the number of dimensions.
    """

    field_id: str
    dims: tuple[str, ...]
    coords: dict[str, Any]
    values: Any = None
    read: Callable[[], Any] | None = None
    unit: str | None = None
    replace_includes_coords: bool = False

    def _expected_shape(self) -> tuple[int, ...]:
        return tuple(len(self.coords[dim]) for dim in self.dims)

    def _coord_arrays(self) -> dict[str, np.ndarray]:
        return {dim: np.asarray(self.coords[dim]) for dim in self.dims}

    def resolve(self) -> np.ndarray:
        raw = self.read() if self.read is not None else self.values
        array = np.asarray(raw, dtype=np.float32)
        expected = self._expected_shape()
        if array.shape != expected:
            # Reshape rather than reject: preserves the old 1-D leniency
            # (a column vector for a labelled series) and validates total size
            # for any rank; a genuine size mismatch raises here.
            array = array.reshape(expected)
        return array

    def field_spec(self) -> FieldSpec:
        return FieldSpec(
            id=self.field_id,
            initial_values=self.resolve(),
            dims=self.dims,
            coords=self._coord_arrays(),
            unit=self.unit,
        )

    def replace_payload(self) -> FieldReplace:
        if self.replace_includes_coords:
            return FieldReplace(
                field_id=self.field_id,
                values=self.resolve(),
                coords=self._coord_arrays(),
            )
        return FieldReplace(field_id=self.field_id, values=self.resolve())


@dataclass
class SeriesProducer:
    """Callable-backed line data sampled per frame into an append-only field.

    Pure producer: owns the readers and the rolling buffer, and emits
    ``FieldAppend`` (live) / ``FieldReplace`` (reset). Presentation is a separate
    public widget declaration; this class carries no view or panel spec.
    """

    name: str
    read: SeriesReaders
    x: Callable[[], float] | None = None
    y_unit: str = "a.u."
    max_samples: int = 2400
    _field_id: str = field(init=False, default="")
    _buf_x: list = field(init=False, default_factory=list)
    _buf_vals: list = field(init=False, default_factory=list)
    _sampled_this_frame: bool = field(init=False, default=False)

    def _register(self, index: int) -> None:
        name_slug = slug(self.name)
        self._field_id = f"field_{index}_{name_slug}"

    def _series(self) -> dict[str, Callable[[], float]]:
        if callable(self.read):
            return {self.name: self.read}
        return dict(self.read)

    def _begin_frame(self) -> None:
        self._sampled_this_frame = False

    def _sample(self) -> None:
        series = self._series()
        self._buf_x.append(self._x_value())
        self._buf_vals.append([reader() for reader in series.values()])
        self._sampled_this_frame = True

    def _x_value(self) -> float:
        if self.x is not None:
            return float(self.x())
        return float(len(self._buf_x))

    def _drain_message(self):
        if not self._buf_x:
            return None
        x_values = self._buf_x[:]
        samples = self._buf_vals[:]
        self._buf_x.clear()
        self._buf_vals.clear()
        values = (
            np.array(samples, dtype=np.float32)
            .reshape(len(x_values), len(self._series()))
            .T
        )
        return update_message(
            FieldAppend(
                field_id=self._field_id,
                append_dim="time",
                values=values,
                coord_values=np.array(x_values, dtype=np.float32),
                max_length=self.max_samples,
            )
        )

    def _field_spec(self) -> FieldSpec:
        series = self._series()
        return FieldSpec(
            id=self._field_id,
            initial_values=np.array(
                [[reader()] for reader in series.values()],
                dtype=np.float32,
            ),
            dims=("series", "time"),
            coords={
                "series": np.array(list(series.keys())),
                "time": np.array([self._x_value()], dtype=np.float32),
            },
            unit=self.y_unit,
        )

    def _replace_message(self):
        series = self._series()
        return update_message(
            FieldReplace(
                field_id=self._field_id,
                values=np.array(
                    [[reader()] for reader in series.values()],
                    dtype=np.float32,
                ),
                coords={
                    "series": np.array(list(series.keys())),
                    "time": np.array([self._x_value()], dtype=np.float32),
                },
            )
        )


@dataclass
class DerivedValueProducer:
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


__all__ = [
    "SnapshotProducer",
    "SeriesProducer",
    "SeriesReaders",
    "DerivedValueProducer",
]
