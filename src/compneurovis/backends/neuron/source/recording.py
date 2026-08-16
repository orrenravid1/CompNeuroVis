"""NEURON source data bindings and optimized reference recorders."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np

from compneurovis.backends.interaction import _selection_ids_from_internal
from compneurovis.backends.neuron.backend import NeuronBackend
from compneurovis.backends.neuron.segment_readers import SegmentValueSource
from compneurovis.core.field import FieldSpec
from compneurovis.core.messages import FieldAppend, FieldReplace
from compneurovis.inline._ids import slug


def _state_value(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        if value.ndim == 0:
            return value.item()
        return value.tolist()
    return value


@dataclass
class SegmentVariableDisplayBinding:
    name: str
    variable: str
    source: SegmentValueSource
    unit: str | None = None
    color_limits: tuple[float, float] | None = None
    color_map: str = "scalar"
    _field_id: str = field(init=False, default="")
    _state_update: Callable[[], None] | None = field(
        init=False, default=None, repr=False
    )

    def __post_init__(self) -> None:
        if not str(self.variable).strip():
            raise ValueError("segment variable display needs a variable name")

    def _register(self, index: int) -> None:
        suffix = f"{index}_{slug(self.name)}"
        self._field_id = f"segment_variable_display_{suffix}"

    def _bind_state_updates(self, emit: Callable[[], None]) -> None:
        self._state_update = emit

    def set_display(
        self,
        *,
        name: str,
        data: SegmentValueSource,
        unit: str | None = None,
        color_limits: tuple[float, float] | None = None,
        color_map: str = "scalar",
    ) -> None:
        """Replace the one live source and presentation carried by this field."""

        resolved_name = str(name)
        resolved_map = str(color_map)
        same_source = (
            self.source == data
            if isinstance(self.source, str) and isinstance(data, str)
            else self.source is data
        )
        if (
            self.variable == resolved_name
            and same_source
            and self.unit == unit
            and self.color_limits == color_limits
            and self.color_map == resolved_map
        ):
            return
        self.variable = resolved_name
        self.source = data
        self.unit = unit
        self.color_limits = color_limits
        self.color_map = resolved_map
        if self._state_update is not None:
            self._state_update()

    def _initial_field(self, backend: NeuronBackend) -> FieldSpec:
        return FieldSpec(
            id=self._field_id,
            initial_values=self._read_values(backend),
            dims=("segment",),
            coords={"segment": np.asarray(backend.geometry.entity_ids)},
            # FieldReplace carries attrs but not unit, so a retarget can only
            # republish one of the two. Attrs is that one; leaving FieldSpec.unit
            # set here would strand a stale copy after the first set_display.
            attrs=self._field_attrs(),
        )

    def _replace_payload(self, backend: NeuronBackend) -> FieldReplace:
        return FieldReplace(
            field_id=self._field_id,
            values=self._read_values(backend),
            attrs_update=self._field_attrs(),
        )

    def _field_attrs(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "variable": self.variable,
            "unit": self.unit or "",
        }
        limits = self.color_limits
        attrs["color_limits"] = None if limits is None else tuple(float(value) for value in limits)
        attrs["color_map"] = self.color_map
        return attrs

    def _read_values(self, backend: NeuronBackend) -> np.ndarray:
        return backend.segment_readers.read(backend, self.source)


class SegmentVariableDisplayRef:
    __slots__ = ("_binding",)

    def __init__(self, binding: SegmentVariableDisplayBinding) -> None:
        self._binding = binding

    @property
    def field_id(self) -> str:
        return self._binding._field_id

    def set_display(
        self,
        *,
        name: str,
        data: SegmentValueSource,
        unit: str | None = None,
        color_limits: tuple[float, float] | None = None,
        color_map: str = "scalar",
    ) -> None:
        self._binding.set_display(
            name=name,
            data=data,
            unit=unit,
            color_limits=color_limits,
            color_map=color_map,
        )



@dataclass
class SegmentVariableHistoryBinding:
    """Time history of one or more quantities over the selected segments.

    A history either declares its own `variables` or follows a
    `display_binding`, never both: a follower's quantity and unit are whatever
    its display currently shows, so declaring variables alongside one would
    leave a second, silently ignored source of truth.
    """

    name: str
    selection_id: str
    variables: dict[str, SegmentValueSource] = field(default_factory=dict)
    unit: str = ""
    max_samples: int = 5000
    display_binding: SegmentVariableDisplayBinding | None = None
    include_variable_dim: bool = True
    _field_id: str = field(init=False, default="")

    def __post_init__(self) -> None:
        if self.display_binding is not None:
            if self.variables:
                raise ValueError(
                    "segment variable history follows its display binding; "
                    "it must not also declare variables"
                )
            return
        if not self.variables:
            raise ValueError("segment variable history needs at least one variable")
        if not self.include_variable_dim and len(self.variables) != 1:
            raise ValueError(
                "history without a variable dimension needs exactly one variable"
            )

    def _register(self, index: int) -> None:
        suffix = f"{index}_{slug(self.name)}"
        self._field_id = f"segment_variable_history_{suffix}"

    def _active_variables(self) -> tuple[tuple[str, SegmentValueSource], ...]:
        if self.display_binding is None:
            return tuple(self.variables.items())
        return ((self.display_binding.variable, self.display_binding.source),)

    def _selected_segment_ids(self, backend: NeuronBackend) -> list[str]:
        return [
            entity_id
            for entity_id in _selection_ids_from_internal(
                backend.values.get(self.selection_id)
            )
            if entity_id in backend._entity_index_by_id
        ]

    def _sample_selected(self, backend: NeuronBackend) -> np.ndarray:
        sections_by_name = backend.sections_by_name()
        selected_ids = self._selected_segment_ids(backend)
        active_variables = self._active_variables()
        readers = backend.segment_readers
        values = np.empty(
            (len(active_variables), len(selected_ids)), dtype=np.float32
        )
        for segment_index, entity_id in enumerate(selected_ids):
            index = backend._entity_index_by_id[entity_id]
            section_name = str(backend.geometry.section_names[index])
            xloc = float(backend.geometry.xlocs[index])
            seg = sections_by_name[section_name](xloc)
            for variable_index, (_, source) in enumerate(active_variables):
                # Each producer knows how to answer for one segment: a range
                # variable reads the segment, an array indexes, a derived
                # quantity composes its inputs at that segment.
                values[variable_index, segment_index] = readers.sample(
                    backend, source, seg, index
                )
        return values

    def _initial_field(self, backend: NeuronBackend) -> FieldSpec:
        from neuron import h

        selected_ids = self._selected_segment_ids(backend)
        variable_names = tuple(name for name, _ in self._active_variables())
        values = self._sample_selected(backend)
        if not self.include_variable_dim:
            follows_display = self.display_binding is not None
            unit = self.display_binding.unit if follows_display else self.unit
            return FieldSpec(
                id=self._field_id,
                initial_values=values.reshape(len(selected_ids), 1),
                dims=("segment", "time"),
                coords={
                    "segment": np.asarray(selected_ids),
                    "time": np.asarray([float(h.t)], dtype=np.float32),
                },
                # A trace that follows a display retargets with it, and
                # FieldReplace can republish only attrs -- so attrs owns the
                # unit there. A standalone trace's unit is fixed at authoring.
                unit=None if follows_display else unit,
                attrs={"variable": variable_names[0], "unit": unit or ""},
            )
        return FieldSpec(
            id=self._field_id,
            initial_values=values.reshape(
                len(variable_names), len(selected_ids), 1
            ),
            dims=("variable", "segment", "time"),
            coords={
                "variable": np.asarray(variable_names),
                "segment": np.asarray(selected_ids),
                "time": np.asarray([float(h.t)], dtype=np.float32),
            },
            unit=self.unit,
        )

    def _replace_payload(self, backend: NeuronBackend) -> FieldReplace:
        field = self._initial_field(backend)
        return FieldReplace(
            field_id=self._field_id,
            values=field.initial_values,
            coords=dict(field.coords),
            attrs_update=dict(field.attrs),
        )

    def _append_payload(self, backend: NeuronBackend, times_array: np.ndarray, samples: Sequence[np.ndarray]) -> FieldAppend:
        del backend
        active_count = len(self._active_variables())
        segment_count = samples[0].shape[1] if samples else 0
        values = np.stack(samples, axis=2).reshape(
            active_count, segment_count, len(samples)
        )
        if not self.include_variable_dim:
            values = values.reshape(segment_count, len(samples))
        return FieldAppend(
            field_id=self._field_id,
            append_dim="time",
            values=values.astype(np.float32),
            coord_values=times_array,
            max_length=self.max_samples,
        )

@dataclass
class NeuronRefRecorder:
    """PtrVector-backed recorder for NEURON refs declared through source()."""

    field_id: str
    series_dim: str
    series: tuple[str, ...]
    refs: tuple[Any, ...]
    max_samples: int = 5000
    sample_dt: float | None = None
    _ptr_vector: Any = field(init=False, default=None)
    _values_vector: Any = field(init=False, default=None)
    _last_emit_t: float | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        if len(self.refs) != len(self.series):
            raise ValueError("record_refs(...) refs and series must have the same length")

    def sample_vector(self) -> np.ndarray:
        if self._ptr_vector is None:
            self._build_ptr_vector()
        self._ptr_vector.gather(self._values_vector)
        return np.asarray(self._values_vector.as_numpy(), dtype=np.float32).copy()

    def replace_payload(self) -> FieldReplace:
        """A one-sample FieldReplace at the current time -- clears this plot's
        scrolling history in the frontend (backs ``ctx.clear``)."""
        from neuron import h

        values = self.sample_vector().reshape(len(self.series), 1).astype(np.float32)
        self.mark_emitted(float(h.t))
        return FieldReplace(
            field_id=self.field_id,
            values=values,
            coords={
                self.series_dim: np.asarray(self.series),
                "time": np.asarray([float(h.t)], dtype=np.float32),
            },
        )

    def mark_emitted(self, t: float) -> None:
        self._last_emit_t = float(t)

    def sample_indices(self, times: np.ndarray) -> np.ndarray:
        sample_dt = self.sample_dt
        if sample_dt is None or sample_dt <= 0:
            if len(times):
                self.mark_emitted(float(times[-1]))
            return np.arange(len(times), dtype=np.int32)
        if len(times) == 0:
            return np.asarray([], dtype=np.int32)

        interval = float(sample_dt)
        eps = max(1e-9, interval * 1e-6)
        next_t = float(times[0]) if self._last_emit_t is None else self._last_emit_t + interval
        selected: list[int] = []
        for index, raw_t in enumerate(times):
            t = float(raw_t)
            if t + eps < next_t:
                continue
            selected.append(index)
            while next_t <= t + eps:
                next_t += interval
        if selected:
            self.mark_emitted(float(times[selected[-1]]))
        return np.asarray(selected, dtype=np.int32)

    def _build_ptr_vector(self) -> None:
        from neuron import h

        self._ptr_vector = h.PtrVector(len(self.refs))
        self._values_vector = h.Vector(len(self.refs))
        for index, ref in enumerate(self.refs):
            self._ptr_vector.pset(index, ref)


def _recorder_sample_indices(recorder: Any, times_array: np.ndarray) -> np.ndarray:
    sample_indices = getattr(recorder, "sample_indices", None)
    if callable(sample_indices):
        return sample_indices(times_array)
    return np.arange(len(times_array), dtype=np.int32)


def _resolve_ref_record_max_samples(
    *,
    explicit: int | None,
    rolling_window: Any,
    sample_dt: float | None,
    sim_dt: float,
) -> int:
    if explicit is not None:
        return int(explicit)
    window = None if rolling_window is None else float(rolling_window)
    cadence = sample_dt if sample_dt is not None and sample_dt > 0 else sim_dt
    if window is not None and cadence > 0:
        return max(1, int(math.ceil(window / float(cadence))) + 2)
    return 5000

__all__ = [
    "NeuronRefRecorder",
    "SegmentValueSource",
    "SegmentVariableDisplayBinding",
    "SegmentVariableDisplayRef",
    "SegmentVariableHistoryBinding",
]
