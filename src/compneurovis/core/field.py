from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

import numpy as np

from compneurovis.core._immutability import (
    FrozenDict,
    freeze_spec_data,
    readonly_1d_array,
    readonly_array,
)
from compneurovis.core.specs import IdentifiedSpec, SpecBase


def _coerce_coord(value: Any) -> np.ndarray:
    arr = np.asarray(value)
    if arr.ndim != 1:
        raise ValueError("Field coordinates must be one-dimensional")
    return arr


@dataclass(frozen=True, slots=True)
class Field:
    """Dense labeled array with named axes and coordinate metadata."""

    id: str
    values: np.ndarray
    dims: tuple[str, ...]
    coords: Mapping[str, np.ndarray]
    unit: str | None = None
    attrs: Mapping[str, Any] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        values = readonly_array(self.values)
        dims = tuple(self.dims)
        coords = {
            str(name): readonly_1d_array(
                coord,
                error="Field coordinates must be one-dimensional",
            )
            for name, coord in self.coords.items()
        }

        if values.ndim != len(dims):
            raise ValueError(
                f"Field '{self.id}' has {values.ndim} dimensions but dims={dims}"
            )
        if set(coords.keys()) != set(dims):
            raise ValueError(
                f"Field '{self.id}' coords keys must exactly match dims {dims}"
            )
        for axis, dim in enumerate(dims):
            if len(coords[dim]) != values.shape[axis]:
                raise ValueError(
                    f"Field '{self.id}' coord '{dim}' has length {len(coords[dim])}, "
                    f"expected {values.shape[axis]}"
                )

        object.__setattr__(self, "values", values)
        object.__setattr__(self, "dims", dims)
        object.__setattr__(self, "coords", FrozenDict(coords))
        object.__setattr__(
            self,
            "attrs",
            freeze_spec_data(self.attrs, path=f"Field[{self.id!r}].attrs"),
        )

    def axis_index(self, dim: str) -> int:
        try:
            return self.dims.index(dim)
        except ValueError as exc:
            raise KeyError(f"Unknown dimension '{dim}' for field '{self.id}'") from exc

    def coord(self, dim: str) -> np.ndarray:
        return self.coords[dim]

    def with_values(
        self,
        values: np.ndarray,
        coords: Mapping[str, np.ndarray] | None = None,
        attrs_update: Mapping[str, Any] | None = None,
    ) -> Field:
        merged_attrs = dict(self.attrs)
        if attrs_update:
            merged_attrs.update(attrs_update)
        return Field(
            id=self.id,
            values=np.asarray(values),
            dims=self.dims,
            coords=dict(self.coords if coords is None else coords),
            unit=self.unit,
            attrs=merged_attrs,
        )

    def append(
        self,
        dim: str,
        values: np.ndarray,
        coord_values: np.ndarray,
        *,
        max_length: int | None = None,
        attrs_update: Mapping[str, Any] | None = None,
    ) -> Field:
        axis = self.axis_index(dim)
        append_values = np.asarray(values)
        append_coords = _coerce_coord(coord_values)

        if append_values.ndim != self.values.ndim:
            raise ValueError(
                f"Field '{self.id}' append values must have ndim {self.values.ndim}, "
                f"got {append_values.ndim}"
            )
        if append_values.shape[axis] != len(append_coords):
            raise ValueError(
                f"Field '{self.id}' append coord '{dim}' has length {len(append_coords)}, "
                f"expected {append_values.shape[axis]}"
            )
        for other_axis, other_dim in enumerate(self.dims):
            if other_axis == axis:
                continue
            if append_values.shape[other_axis] != self.values.shape[other_axis]:
                raise ValueError(
                    f"Field '{self.id}' append shape mismatch on dim '{other_dim}': "
                    f"{append_values.shape[other_axis]} != {self.values.shape[other_axis]}"
                )

        new_coords = dict(self.coords)
        if max_length is not None and max_length >= 0:
            max_length = int(max_length)
            if max_length == 0:
                slicers = [slice(None)] * self.values.ndim
                slicers[axis] = slice(0, 0)
                new_values = self.values[tuple(slicers)]
                new_coords[dim] = self.coords[dim][:0]
            elif append_values.shape[axis] >= max_length:
                slicers = [slice(None)] * append_values.ndim
                slicers[axis] = slice(-max_length, None)
                new_values = append_values[tuple(slicers)]
                new_coords[dim] = append_coords[-max_length:]
            else:
                keep_existing = max_length - append_values.shape[axis]
                slicers = [slice(None)] * self.values.ndim
                slicers[axis] = slice(-keep_existing, None)
                existing_values = self.values[tuple(slicers)]
                existing_coords = self.coords[dim][-keep_existing:]
                new_values = np.concatenate([existing_values, append_values], axis=axis)
                new_coords[dim] = np.concatenate([existing_coords, append_coords], axis=0)
        else:
            new_values = np.concatenate([self.values, append_values], axis=axis)
            new_coords[dim] = np.concatenate([self.coords[dim], append_coords], axis=0)

        merged_attrs = dict(self.attrs)
        if attrs_update:
            merged_attrs.update(attrs_update)

        return Field(
            id=self.id,
            values=new_values,
            dims=self.dims,
            coords=new_coords,
            unit=self.unit,
            attrs=merged_attrs,
        )

    def resolve_indexer(self, dim: str, selector: Any) -> int | slice | np.ndarray:
        coord = self.coord(dim)
        if isinstance(selector, slice):
            return selector
        if isinstance(selector, Mapping):
            expected = {"kind", "start", "stop", "step"}
            if selector.get("kind") != "slice" or set(selector) != expected:
                raise TypeError(
                    f"Unsupported selector mapping for field '{self.id}' dim '{dim}'"
                )
            return slice(
                selector["start"],
                selector["stop"],
                selector["step"],
            )
        if isinstance(selector, (int, np.integer)):
            return int(selector)
        if isinstance(selector, (list, tuple, np.ndarray)):
            selector_array = np.asarray(selector)
            if selector_array.ndim != 1:
                raise TypeError(
                    f"Unsupported selector shape {selector_array.shape!r} for field '{self.id}' dim '{dim}'"
                )
            if selector_array.size == 0:
                return np.asarray([], dtype=np.int32)
            if np.issubdtype(selector_array.dtype, np.integer):
                return selector_array.astype(np.int32)
            if np.issubdtype(selector_array.dtype, np.floating):
                if not np.issubdtype(coord.dtype, np.number):
                    raise TypeError(
                        f"Field '{self.id}' coord '{dim}' is not numeric, cannot resolve float selectors"
                    )
                indices = [int(np.argmin(np.abs(coord.astype(float) - float(value)))) for value in selector_array]
                return np.asarray(indices, dtype=np.int32)
            selector_strings = selector_array.astype(str)
            resolved = []
            coord_strings = coord.astype(str)
            for value in selector_strings:
                matches = np.where(coord_strings == value)[0]
                if not len(matches):
                    raise KeyError(
                        f"Field '{self.id}' coord '{dim}' does not contain label '{value}'"
                    )
                resolved.append(int(matches[0]))
            return np.asarray(resolved, dtype=np.int32)
        if isinstance(selector, str):
            matches = np.where(coord.astype(str) == selector)[0]
            if not len(matches):
                raise KeyError(
                    f"Field '{self.id}' coord '{dim}' does not contain label '{selector}'"
                )
            return int(matches[0])
        if isinstance(selector, (float, np.floating)):
            if not np.issubdtype(coord.dtype, np.number):
                raise TypeError(
                    f"Field '{self.id}' coord '{dim}' is not numeric, cannot resolve float selector"
                )
            return int(np.argmin(np.abs(coord.astype(float) - float(selector))))
        raise TypeError(
            f"Unsupported selector type {type(selector)!r} for field '{self.id}' dim '{dim}'"
        )

    def select(self, selectors: Mapping[str, Any]) -> Field:
        remaining_dims: list[str] = list(self.dims)
        remaining_coords = dict(self.coords)
        values = self.values

        for dim, selector in selectors.items():
            axis = remaining_dims.index(dim)
            indexer = self.resolve_indexer(dim, selector)
            if isinstance(indexer, slice):
                slicers = [slice(None)] * values.ndim
                slicers[axis] = indexer
                values = values[tuple(slicers)]
                remaining_coords[dim] = remaining_coords[dim][indexer]
                continue
            if isinstance(indexer, np.ndarray):
                values = np.take(values, indexer, axis=axis)
                remaining_coords[dim] = remaining_coords[dim][indexer]
                continue
            values = np.take(values, indexer, axis=axis)
            remaining_dims.remove(dim)
            remaining_coords.pop(dim, None)

        ordered_coords = {dim: remaining_coords[dim] for dim in remaining_dims}
        return Field(
            id=self.id,
            values=np.asarray(values),
            dims=tuple(remaining_dims),
            coords=ordered_coords,
            unit=self.unit,
            attrs=dict(self.attrs),
        )


@dataclass(frozen=True, slots=True)
class FieldRetentionSpec(SpecBase):
    """Consumer-declared minimum history retained by a field producer."""

    append_dim: str
    min_duration: float | None = None
    min_samples: int | None = None

    def __post_init__(self) -> None:
        if not self.append_dim:
            raise ValueError("Field retention append_dim must be non-empty")
        if self.min_duration is not None and self.min_duration < 0:
            raise ValueError("Field retention min_duration must be non-negative")
        if self.min_samples is not None and self.min_samples < 1:
            raise ValueError("Field retention min_samples must be positive")
        if self.min_duration is None and self.min_samples is None:
            raise ValueError(
                "Field retention requires min_duration or min_samples"
            )


@dataclass(frozen=True, slots=True)
class FieldSpec(IdentifiedSpec):
    """Declarative blueprint for a field — schema plus declared initial condition.

    A spec is composed of specs: ``FieldSpec`` lives in ``AppSpec`` alongside
    ``ViewSpec``/``ControlSpec``/``PanelSpec``. It declares the axes (``dims``),
    the coordinate schema (``coords``), ``unit``/``attrs``, and the *initial*
    values the app starts from — the same role ``default_value`` plays for a
    control. It carries no runtime mutation behaviour: the evolving array is
    projection state, materialized as a :class:`Field` value view.
    ``FieldSpec`` is never rebound at runtime.
    """

    initial_values: np.ndarray
    dims: tuple[str, ...]
    coords: Mapping[str, np.ndarray]
    unit: str | None = None
    attrs: Mapping[str, Any] = field(default_factory=FrozenDict)
    retention: tuple[FieldRetentionSpec, ...] = ()

    def __post_init__(self) -> None:
        initial_values = readonly_array(self.initial_values)
        dims = tuple(self.dims)
        coords = {
            str(name): readonly_1d_array(
                coord,
                error="Field coordinates must be one-dimensional",
            )
            for name, coord in self.coords.items()
        }

        if initial_values.ndim != len(dims):
            raise ValueError(
                f"FieldSpec '{self.id}' has {initial_values.ndim} dimensions but dims={dims}"
            )
        if set(coords.keys()) != set(dims):
            raise ValueError(
                f"FieldSpec '{self.id}' coords keys must exactly match dims {dims}"
            )
        for axis, dim in enumerate(dims):
            if len(coords[dim]) != initial_values.shape[axis]:
                raise ValueError(
                    f"FieldSpec '{self.id}' coord '{dim}' has length {len(coords[dim])}, "
                    f"expected {initial_values.shape[axis]}"
                )

        object.__setattr__(self, "initial_values", initial_values)
        object.__setattr__(self, "dims", dims)
        object.__setattr__(self, "coords", FrozenDict(coords))
        object.__setattr__(
            self,
            "attrs",
            freeze_spec_data(self.attrs, path=f"FieldSpec[{self.id!r}].attrs"),
        )
        retention = tuple(self.retention)
        if any(type(item) is not FieldRetentionSpec for item in retention):
            raise TypeError(
                "FieldSpec.retention must contain only core FieldRetentionSpec values"
            )
        object.__setattr__(self, "retention", retention)

    def materialize(self) -> Field:
        """Build the runtime value view from the declared initial condition."""
        return Field(
            id=self.id,
            values=np.array(self.initial_values, copy=True),
            dims=self.dims,
            coords={name: np.array(coord, copy=True) for name, coord in self.coords.items()},
            unit=self.unit,
            attrs=dict(self.attrs),
        )
