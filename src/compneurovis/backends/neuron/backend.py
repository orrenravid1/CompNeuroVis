from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import math
from typing import Any, Callable, Sequence

import numpy as np

from compneurovis.core.controls import ActionSpec
from compneurovis.core.app_spec import AppSpec
from compneurovis.core.field import FieldSpec
from compneurovis.core.views import LinePlotViewSpec
from compneurovis.inline.app_compiler import StartupData
from compneurovis.backends import BackendBase, HistoryCaptureMode
from compneurovis.core.messages import EntityClicked, FieldAppend, FieldReplace, InvokeAction, KeyPressed, Reset, ValueChange
from compneurovis.backends.neuron.geometry import build_morphology_geometry
from compneurovis.backends.interaction import (
    BackendInteractionContext,
    SELECTED_ENTITY_ID_KEY,
    SELECTED_ENTITY_IDS_KEY,
    _selection_ids_from_internal,
)

DISPLAY_FIELD_ID = "segment_display"
HISTORY_FIELD_ID = "segment_history"
TRACE_FIELD_ID = HISTORY_FIELD_ID


@dataclass(frozen=True)
class DisplayConfig:
    """Explicit declaration of the per-segment scalar a NEURON view renders.

    There is no privileged display variable: the morphology coloring and the
    selection trace both read whatever ``ref_of`` points at (e.g. membrane
    voltage, a calcium concentration, a gating current). The model names it.
    """

    ref_of: Callable[[Any], Any]  # segment -> NEURON pointer ref, e.g. seg._ref_v
    unit: str | None = None
    color_limits: tuple[float, float] | None = None
    color_map: str = "scalar"
    color_norm: str = "auto"
    selected_entity_ids: tuple[str, ...] = ()
    select_multiple: bool = False


class NeuronBackend(BackendBase, ABC):
    """Base class for live NEURON-backed CompNeuroVis sessions."""

    HISTORY_CAPTURE_ON_DEMAND = HistoryCaptureMode.ON_DEMAND
    HISTORY_CAPTURE_FULL = HistoryCaptureMode.FULL

    def __init__(
        self,
        *,
        dt: float = 0.1,
        v_init: float = -65.0,
        max_samples: int = 1000,
        display_dt: float | None = 0.1,
        history_capture_mode: HistoryCaptureMode | str = HistoryCaptureMode.ON_DEMAND,
        display: DisplayConfig | None = None,
        history_enabled: bool = False,
        title: str = "CompNeuroVis",
    ):
        super().__init__()
        self.dt = dt
        self.v_init = v_init
        self.max_samples = max_samples
        self.display_dt = display_dt
        self.history_capture_mode = HistoryCaptureMode(history_capture_mode)
        self._display = display
        self._history_enabled = bool(history_enabled)
        self.title = title
        self.sections = None
        self.geometry = None
        self._segment_refs = None
        self._segment_vector = None
        self._recorded_names: list[str] = []
        self._recorded_refs: list[Any] = []
        self._recorded_ptrs = None
        self._recorded_vector = None
        self._runtime_handles = None
        self._field_max_samples: dict[str, int] = {}
        self._entity_index_by_id: dict[str, int] = {}
        self._last_time_value: float | None = None
        self._last_display_values: np.ndarray | None = None
        self._last_voltage_values: np.ndarray | None = None
        self._trace_segment_ids: list[str] = []
        self._trace_history_times: list[float] = []
        self._trace_history_values_by_id: dict[str, list[float]] = {}
        self._trace_refs_key: tuple[str, ...] | None = None
        self._trace_refs = None
        self._trace_vector = None
        # Emission is coalesced: steps are buffered and flushed to the frontend at
        # most every `_flush_dt` sim-ms (0 = flush every tick, the default). This
        # lives on the backend so its runtime is complete standalone; a source that
        # wants coalescing just sets `_flush_dt`.
        self._flush_dt: float = 0.0
        self._pending_times: list[float] = []
        self._pending_steps: list[Any] = []
        self._pending_recorded: list[np.ndarray] = []
        self._last_flush_t: float | None = None

    @abstractmethod
    def build_sections(self):
        """Return the NEURON sections that define the model morphology."""

        pass

    def setup_model(self, sections):
        """Insert mechanisms, stimuli, or recorders after sections are created."""

        return None


    def action_specs(self) -> dict[str, ActionSpec]:
        return {}

    def display_field_id(self) -> str:
        return DISPLAY_FIELD_ID

    def history_field_id(self) -> str:
        return HISTORY_FIELD_ID

    def set_history_enabled(self, enabled: bool = True) -> None:
        self._history_enabled = bool(enabled)

    def history_enabled(self) -> bool:
        return self._history_enabled

    def _require_display(self) -> DisplayConfig:
        if self._display is None:
            raise RuntimeError(
                "No display variable configured. Declare the per-segment scalar the "
                "morphology/selection-trace shows via the source's .display(...)."
            )
        return self._display

    def display_unit(self) -> str | None:
        return self._display.unit if self._display is not None else None

    def history_unit(self) -> str | None:
        return self.display_unit()

    def apply_control(self, control_id: str, value) -> bool:
        try:
            setattr(self, control_id, value)
            return True
        except Exception:
            return False

    def apply_action(self, action_id: str, payload: dict[str, object]) -> bool:
        del action_id, payload
        return False

    def on_action(self, action_id: str, payload: dict[str, Any], context) -> bool:
        del action_id, payload, context
        return False

    def on_key_press(self, key: str, context) -> bool:
        del key, context
        return False

    def on_entity_clicked(self, entity_id: str, context) -> bool:
        del entity_id, context
        return False

    def _after_entity_selection_changed(self, entity_id: str, context) -> None:
        del entity_id, context

    def should_capture_trace_on_click(self, entity_id: str, context) -> bool:
        del entity_id, context
        return True

    def record(self, name: str, ref: Any) -> None:
        """Register one NEURON variable ref for batched PtrVector sampling."""

        self.record_many((name,), (ref,))

    def record_many(self, names: Sequence[str], refs: Sequence[Any]) -> None:
        """Register NEURON variable refs for sampling once per fadvance step."""

        if len(names) != len(refs):
            raise ValueError("NeuronBackend record_many names and refs must have the same length")
        normalized_names = tuple(str(name) for name in names)
        if len(set(normalized_names)) != len(normalized_names):
            raise ValueError("NeuronBackend record_many names must be unique")
        duplicates = set(normalized_names).intersection(self._recorded_names)
        if duplicates:
            duplicate_names = ", ".join(sorted(duplicates))
            raise ValueError(f"NeuronBackend already records: {duplicate_names}")
        self._recorded_names.extend(normalized_names)
        self._recorded_refs.extend(refs)
        self._rebuild_recorded_ptrs()

    def on_recorded_samples(self, times: np.ndarray, values: dict[str, np.ndarray]) -> None:
        """Handle one batched set of values registered with record()/record_many()."""

        del times, values

    def _initialize_model(self) -> tuple[float, np.ndarray | None]:
        """Build the NEURON model and run finitialize.

        The morphology display field (geometry, per-segment sampling, trace
        capture) is optional: it exists only when a display variable was declared.
        With no display this builds and initializes the model exactly the same,
        just without that per-segment sampling layer — returning ``None`` values.
        """

        from neuron import h

        self.sections = self.build_sections()
        self._runtime_handles = self.setup_model(self.sections)
        self._recorded_names.clear()
        self._recorded_refs.clear()
        self._recorded_ptrs = None
        self._recorded_vector = None
        self._invalidate_trace_sampler()

        if self._display is not None:
            self.geometry = build_morphology_geometry(self.sections)
            self._entity_index_by_id = {entity_id: index for index, entity_id in enumerate(self.geometry.entity_ids)}
            self._prepare_recorders()
            self._set_initial_selection_values()
        else:
            self.geometry = None
            self._entity_index_by_id = {}
            self.values.set(SELECTED_ENTITY_IDS_KEY, [])

        h.dt = self.dt
        h.finitialize(self.v_init)

        if self._display is None:
            self._last_time_value = float(h.t)
            self._last_display_values = None
            self._last_voltage_values = None
            self._clear_trace_history()
            return float(h.t), None

        time_value, display_values = self._sample()
        self._last_time_value = float(time_value)
        self._last_display_values = np.asarray(display_values, dtype=np.float32)
        self._last_voltage_values = self._last_display_values
        if self._history_enabled:
            self._initialize_trace_history(time_value, display_values)
        else:
            self._clear_trace_history()
        return time_value, display_values

    def build_startup_data(self) -> StartupData:
        """Build NEURON model and return simulator data. Sources add views/panels."""

        self._initialize_model()
        if self._display is None:
            return StartupData(title=self.title)
        display_field = FieldSpec(
            id=self.display_field_id(),
            initial_values=np.asarray(self._last_display_values, dtype=np.float32),
            dims=("segment",),
            coords={"segment": np.asarray(self.geometry.entity_ids)},
            unit=self.display_unit(),
        )
        fields: list[FieldSpec] = [display_field]
        if self._history_enabled:
            trace_segment_ids, trace_times, trace_values = self._trace_field_snapshot()
            history_unit = self.display_unit() if self.history_unit() is None else self.history_unit()
            fields.append(
                FieldSpec(
                    id=self.history_field_id(),
                    initial_values=np.asarray(trace_values, dtype=np.float32),
                    dims=("segment", "time"),
                    coords={
                        "segment": np.asarray(trace_segment_ids),
                        "time": np.asarray(trace_times, dtype=np.float32),
                    },
                    unit=history_unit,
                )
            )
        return StartupData(fields=tuple(fields), geometries=(self.geometry,), title=self.title)

    def initialize(self, app_spec: AppSpec | None) -> None:
        if self._history_enabled:
            self._field_max_samples[self.history_field_id()] = self._resolved_field_max_samples(
                app_spec,
                field_id=self.history_field_id(),
                append_dim="time",
            )
        self._set_initial_selection_values()
        selected_entity_ids = self._selected_entity_ids_from_values()
        updates: dict[str, Any] = {SELECTED_ENTITY_IDS_KEY: selected_entity_ids}
        if selected_entity_ids and self.geometry is not None:
            initial_entity_id = selected_entity_ids[0]
            updates[SELECTED_ENTITY_ID_KEY] = initial_entity_id
            updates["selected_entity_label"] = self.geometry.label_for(initial_entity_id)
        for key, value in updates.items():
            self.values.set(key, value)
        self.emit_update(ValueChange(updates))

    def _set_initial_selection_values(self) -> None:
        selected_entity_ids = [] if self._display is None else list(self._display.selected_entity_ids)
        if self.geometry is not None:
            selected_entity_ids = [
                entity_id for entity_id in selected_entity_ids
                if entity_id in self._entity_index_by_id
            ]
        self.values.set(SELECTED_ENTITY_IDS_KEY, selected_entity_ids)
        if selected_entity_ids and self.geometry is not None:
            selected_entity_id = selected_entity_ids[0]
            self.values.set(SELECTED_ENTITY_ID_KEY, selected_entity_id)
            self.values.set("selected_entity_label", self.geometry.label_for(selected_entity_id))

    def _prepare_recorders(self):
        from neuron import h

        idx_by_name = {}
        for index, sec in enumerate(self.sections):
            idx_by_name.setdefault(sec.name(), []).append(index)

        section_lookup = {sec.name(): sec for sec in self.sections}
        entity_sections = []
        entity_xlocs = []
        for entity_id, section_name, xloc in zip(self.geometry.entity_ids, self.geometry.section_names, self.geometry.xlocs):
            del entity_id
            entity_sections.append(section_lookup[section_name])
            entity_xlocs.append(float(xloc))

        ref_of = self._require_display().ref_of
        self._segment_refs = h.PtrVector(len(entity_sections))
        self._segment_vector = h.Vector(len(entity_sections))
        for i, (section, xloc) in enumerate(zip(entity_sections, entity_xlocs)):
            self._segment_refs.pset(i, ref_of(section(xloc)))

    def _read_display_values(self) -> np.ndarray:
        self._segment_refs.gather(self._segment_vector)
        return np.asarray(self._segment_vector.as_numpy(), dtype=np.float32).copy()

    def _invalidate_trace_sampler(self) -> None:
        self._trace_refs_key = None
        self._trace_refs = None
        self._trace_vector = None

    def _rebuild_trace_sampler(self) -> None:
        from neuron import h

        key = tuple(self._trace_segment_ids)
        if key == self._trace_refs_key:
            return
        self._trace_refs_key = key
        if not key:
            self._trace_refs = None
            self._trace_vector = None
            return
        ref_of = self._require_display().ref_of
        section_lookup = {sec.name(): sec for sec in self.sections}
        self._trace_refs = h.PtrVector(len(key))
        self._trace_vector = h.Vector(len(key))
        for ptr_index, entity_id in enumerate(key):
            entity_index = self._entity_index_by_id[entity_id]
            section_name = str(self.geometry.section_names[entity_index])
            xloc = float(self.geometry.xlocs[entity_index])
            self._trace_refs.pset(ptr_index, ref_of(section_lookup[section_name](xloc)))

    def _read_selected_trace_values(self) -> np.ndarray:
        if not self._trace_segment_ids:
            return np.empty((0,), dtype=np.float32)
        self._rebuild_trace_sampler()
        self._trace_refs.gather(self._trace_vector)
        return np.asarray(self._trace_vector.as_numpy(), dtype=np.float32).copy()

    def _rebuild_recorded_ptrs(self) -> None:
        from neuron import h

        if not self._recorded_refs:
            self._recorded_ptrs = None
            self._recorded_vector = None
            return
        self._recorded_ptrs = h.PtrVector(len(self._recorded_refs))
        self._recorded_vector = h.Vector(len(self._recorded_refs))
        for index, ref in enumerate(self._recorded_refs):
            self._recorded_ptrs.pset(index, ref)

    def _read_recorded_values(self) -> np.ndarray | None:
        if self._recorded_ptrs is None:
            return None
        self._recorded_ptrs.gather(self._recorded_vector)
        return np.asarray(self._recorded_vector.as_numpy(), dtype=np.float32).copy()

    def recorded_values(self) -> dict[str, float]:
        values = self._read_recorded_values()
        if values is None:
            return {}
        return {name: float(values[index]) for index, name in enumerate(self._recorded_names)}

    def _read_voltage(self) -> np.ndarray:
        return self._read_display_values()

    def _sample(self) -> tuple[float, np.ndarray]:
        from neuron import h

        return float(h.t), self._read_display_values()

    def _initialize_trace_history(self, time_value: float, display_values: np.ndarray) -> None:
        self._last_time_value = float(time_value)
        self._last_display_values = np.asarray(display_values, dtype=np.float32)
        self._last_voltage_values = self._last_display_values
        self._trace_history_times = [float(time_value)]
        self._trace_history_values_by_id = {}
        self._invalidate_trace_sampler()
        if self.history_capture_mode == HistoryCaptureMode.FULL:
            self._trace_segment_ids = list(self.geometry.entity_ids)
            for entity_id in self._trace_segment_ids:
                index = self._entity_index_by_id[entity_id]
                self._trace_history_values_by_id[entity_id] = [float(self._last_display_values[index])]
        else:
            self._trace_segment_ids = []
            for entity_id in self._preferred_trace_entity_ids():
                self._capture_trace_entity(entity_id, include_current_sample=True)

    def _clear_trace_history(self) -> None:
        self._trace_segment_ids = []
        self._trace_history_times = []
        self._trace_history_values_by_id = {}
        self._invalidate_trace_sampler()

    def _selected_entity_ids_from_values(self) -> list[str]:
        selected_entity_ids = self.values.get(SELECTED_ENTITY_IDS_KEY)
        if selected_entity_ids is None:
            return []
        resolved: list[str] = []
        for value in _selection_ids_from_internal(selected_entity_ids):
            if value in self._entity_index_by_id and value not in resolved:
                resolved.append(value)
        return resolved

    def _preferred_trace_entity_ids(self) -> list[str]:
        return self._selected_entity_ids_from_values()

    def _capture_trace_entity(self, entity_id: str, *, include_current_sample: bool) -> bool:
        if entity_id in self._trace_history_values_by_id:
            return False
        index = self._entity_index_by_id.get(entity_id)
        if index is None:
            return False
        history = [math.nan] * len(self._trace_history_times)
        if include_current_sample and history and self._last_display_values is not None:
            history[-1] = float(self._last_display_values[index])
        self._trace_segment_ids.append(entity_id)
        self._trace_history_values_by_id[entity_id] = history
        self._invalidate_trace_sampler()
        return True

    def _trace_field_snapshot(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        times = np.asarray(self._trace_history_times, dtype=np.float32)
        segment_ids = np.asarray(self._trace_segment_ids)
        if not self._trace_segment_ids:
            values = np.empty((0, len(self._trace_history_times)), dtype=np.float32)
        else:
            values = np.asarray(
                [self._trace_history_values_by_id[entity_id] for entity_id in self._trace_segment_ids],
                dtype=np.float32,
            )
        return segment_ids, times, values

    def _trace_field_replace(self) -> FieldReplace:
        trace_segment_ids, trace_times, trace_values = self._trace_field_snapshot()
        return FieldReplace(
            field_id=self.history_field_id(),
            values=trace_values,
            coords={
                "segment": trace_segment_ids,
                "time": trace_times,
            },
        )

    def _display_field_replace(self, display_values: np.ndarray) -> FieldReplace:
        return FieldReplace(
            field_id=self.display_field_id(),
            values=np.asarray(display_values, dtype=np.float32),
        )

    def _trim_selected_trace_history(self, max_length: int) -> None:
        if max_length < 0 or len(self._trace_history_times) <= max_length:
            return
        self._trace_history_times = self._trace_history_times[-max_length:]
        for entity_id in list(self._trace_history_values_by_id.keys()):
            self._trace_history_values_by_id[entity_id] = self._trace_history_values_by_id[entity_id][-max_length:]

    def _append_selected_trace_history(self, batch_values: np.ndarray, times: list[float]) -> None:
        if not self._trace_segment_ids:
            return
        indices = [self._entity_index_by_id[entity_id] for entity_id in self._trace_segment_ids]
        self._append_selected_trace_history_values(batch_values[indices, :], times)

    def _append_selected_trace_history_values(self, values: np.ndarray, times: list[float]) -> None:
        if not self._trace_segment_ids:
            return
        self._trace_history_times.extend(float(time_value) for time_value in times)
        for row_index, entity_id in enumerate(self._trace_segment_ids):
            self._trace_history_values_by_id[entity_id].extend(float(value) for value in values[row_index])
        max_length = self._field_max_samples.get(self.history_field_id())
        if max_length is not None:
            self._trim_selected_trace_history(int(max_length))

    def _emit_on_demand_display_and_trace(
        self,
        times_array: np.ndarray,
        latest_display_values: np.ndarray,
        selected_trace_values: np.ndarray | None,
    ) -> None:
        self._last_time_value = float(times_array[-1])
        self._last_display_values = np.asarray(latest_display_values, dtype=np.float32)
        self._last_voltage_values = self._last_display_values

        self.emit_update(self._display_field_replace(self._last_display_values))

        if self._history_enabled and selected_trace_values is not None and self._trace_segment_ids:
            self._append_selected_trace_history_values(selected_trace_values, times_array.tolist())
            self.emit_update(
                FieldAppend(
                    field_id=self.history_field_id(),
                    append_dim="time",
                    values=selected_trace_values,
                    coord_values=times_array,
                    max_length=self._field_max_samples.get(self.history_field_id(), self.max_samples),
                )
            )

    def sim_ms_per_frame(self) -> float:
        if self.display_dt is None:
            return float(self.dt)
        if self.display_dt <= 0:
            raise ValueError("NeuronBackend display_dt must be positive or None")
        return float(self.display_dt)

    def idle_sleep(self) -> float:
        return 0.0

    def is_active(self) -> bool:
        return True

    def _resolved_field_max_samples(self, app_spec: AppSpec | None, *, field_id: str, append_dim: str) -> int:
        required = int(self.max_samples)
        if self.dt <= 0:
            return required
        # Only a source supplies views (to size the history buffer to a plot's
        # rolling window); standalone the backend initializes with app_spec=None
        # and falls back to its own max_samples.
        if app_spec is None:
            return required
        for view in app_spec.view_catalog.views.values():
            if not isinstance(view, LinePlotViewSpec):
                continue
            if view.field_id != field_id:
                continue
            if view.x_dim != append_dim:
                continue
            if view.rolling_window is None:
                continue
            required = max(required, int(math.ceil(float(view.rolling_window) / float(self.dt))) + 1)
        return required

    def _sample_step(self) -> Any:
        """Return per-step data after each fadvance call.

        Override to sample custom quantities. Whatever you return here is collected
        into a list and passed to _emit_batch() once per display update batch.
        The default returns the current morphology display values array.
        """
        return self._read_display_values()

    def _emit_batch(self, times_array: np.ndarray, steps: list[Any]) -> None:
        """Emit display and history field updates for one batch of fadvance steps.

        Override to emit custom fields. steps is a list of whatever _sample_step()
        returned — one entry per fadvance step in the batch.
        The default handles morphology voltage display and trace/full history.
        """
        self._last_time_value = float(times_array[-1])
        self._last_display_values = np.asarray(steps[-1], dtype=np.float32)
        self._last_voltage_values = self._last_display_values

        self.emit_update(self._display_field_replace(self._last_display_values))

        if not self._history_enabled:
            return

        if self.history_capture_mode == HistoryCaptureMode.FULL:
            batch_values = np.stack(steps, axis=1)
            self.emit_update(
                FieldAppend(
                    field_id=self.history_field_id(),
                    append_dim="time",
                    values=batch_values,
                    coord_values=times_array,
                    max_length=self._field_max_samples.get(self.history_field_id(), self.max_samples),
                )
            )
        else:
            if self._trace_segment_ids:
                selected_indices = [self._entity_index_by_id[entity_id] for entity_id in self._trace_segment_ids]
                selected_values = np.stack(
                    [np.asarray(step, dtype=np.float32)[selected_indices] for step in steps],
                    axis=1,
                )
                self._append_selected_trace_history_values(selected_values, times_array.tolist())
                self.emit_update(
                    FieldAppend(
                        field_id=self.history_field_id(),
                        append_dim="time",
                        values=selected_values,
                        coord_values=times_array,
                        max_length=self._field_max_samples.get(self.history_field_id(), self.max_samples),
                    )
                )

    # -- runtime loop: a complete standalone tick with extension seams ---------

    def _advance(self) -> None:
        """Advance the simulator one step. Override to drive a custom/variable-step solver."""
        from neuron import h
        h.fadvance()

    def _current_sim_time(self) -> float:
        from neuron import h
        return float(h.t)

    def _reset_pending_output_buffers(self) -> None:
        self._pending_times = []
        self._pending_steps = []
        self._pending_recorded = []
        self._last_flush_t = self._current_sim_time()

    def _on_step(self, t: float) -> None:
        """Hook run after each advance. Override to observe per-step signals (e.g. derives)."""
        del t

    def tick(self) -> None:
        """Advance one display frame; buffer the steps and flush per ``_flush_dt``.

        This is the backend's own runtime — it works standalone. A source extends
        it by overriding ``_advance``/``_on_step``/``_sample_step``/``_emit_batch``
        or by setting ``_flush_dt``; it does not replace this loop.
        """
        if self._last_flush_t is None:
            self._last_flush_t = self._current_sim_time()
        t_target = self._current_sim_time() + self.sim_ms_per_frame()
        while True:
            self._advance()
            t = self._current_sim_time()
            self._on_step(t)
            self._pending_times.append(t)
            self._pending_steps.append(self._sample_step())
            recorded = self._read_recorded_values()
            if recorded is not None:
                self._pending_recorded.append(recorded)
            if t >= t_target:
                break
        if (self._current_sim_time() - self._last_flush_t) >= self._flush_dt - 1e-9:
            self._flush_pending()

    def _flush_pending(self) -> None:
        """Emit the buffered steps as one batch and reset the buffers."""
        if not self._pending_steps:
            return
        times_array = np.asarray(self._pending_times, dtype=np.float32)
        self._emit_batch(times_array, self._pending_steps)
        if self._pending_recorded:
            recorded_batch = np.stack(self._pending_recorded, axis=1)
            self.on_recorded_samples(
                times_array,
                {name: recorded_batch[index] for index, name in enumerate(self._recorded_names)},
            )
        self._pending_times = []
        self._pending_steps = []
        self._pending_recorded = []
        self._last_flush_t = self._current_sim_time()

    def _interaction_context(self) -> BackendInteractionContext:
        return BackendInteractionContext(self)

    def _dispatch_action(self, action_id: str, payload: dict[str, Any]) -> bool:
        if self.on_action(action_id, payload, self._interaction_context()):
            return True
        return self.apply_action(action_id, payload)

    def handle(self, message) -> None:
        command = message.payload
        if isinstance(command, Reset):
            from neuron import h

            h.finitialize(self.v_init)
            time_value, display_values = self._sample()
            self._last_time_value = float(time_value)
            self._last_display_values = np.asarray(display_values, dtype=np.float32)
            self._last_voltage_values = self._last_display_values
            if self._history_enabled:
                self._initialize_trace_history(time_value, display_values)
            else:
                self._clear_trace_history()
            self.emit_update(
                self._display_field_replace(display_values)
            )
            if self._history_enabled:
                self.emit_update(self._trace_field_replace())
        elif isinstance(command, ValueChange):
            acted = set(self.values.apply(self, command.updates))
            for key, value in command.updates.items():
                if key not in acted and self.apply_control(key, value):
                    self.values.set(key, value)
        elif isinstance(command, InvokeAction):
            self._dispatch_action(command.action_id, command.payload)
        elif isinstance(command, EntityClicked):
            entity_id = str(command.entity_id)
            self.values.set(SELECTED_ENTITY_ID_KEY, entity_id)
            context = self._interaction_context()

            selection_before = tuple(self._selected_entity_ids_from_values())
            handled = self.on_entity_clicked(entity_id, context)
            selection_after = tuple(self._selected_entity_ids_from_values())
            if not handled and selection_after == selection_before:
                if self._display is not None and self._display.select_multiple:
                    selected_entity_ids = list(selection_before)
                    if entity_id not in selected_entity_ids:
                        selected_entity_ids.append(entity_id)
                else:
                    selected_entity_ids = [entity_id]
                self.values.set(SELECTED_ENTITY_IDS_KEY, selected_entity_ids)

            selected_label = entity_id
            if self.geometry is not None:
                try:
                    selected_label = self.geometry.label_for(entity_id)
                except KeyError:
                    selected_label = entity_id
            update = {
                SELECTED_ENTITY_ID_KEY: entity_id,
                SELECTED_ENTITY_IDS_KEY: list(self._selected_entity_ids_from_values()),
                "selected_entity_label": selected_label,
            }
            for key, value in update.items():
                self.values.set(key, value)
            self.emit_update(ValueChange(update))
            self._after_entity_selection_changed(entity_id, context)

            if (
                self._history_enabled
                and self.history_capture_mode == HistoryCaptureMode.ON_DEMAND
                and self.should_capture_trace_on_click(entity_id, context)
            ):
                if self._capture_trace_entity(entity_id, include_current_sample=True):
                    self.emit_update(self._trace_field_replace())
        elif isinstance(command, KeyPressed):
            self.on_key_press(command.key, self._interaction_context())
