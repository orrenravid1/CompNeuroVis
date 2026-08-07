from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Callable, Sequence

import numpy as np

from compneurovis.core.controls import ActionSpec
from compneurovis.core.app_spec import AppSpec
from compneurovis.core.field import FieldSpec
from compneurovis.backends.compartment import (
    CompartmentHistoryMixin,
    resolved_field_max_samples,
)
from compneurovis.backends.startup import StartupData
from compneurovis.backends import BackendBase, HistoryCaptureMode
from compneurovis.core.messages import (
    EntityClicked,
    FieldAppend,
    InvokeAction,
    KeyPressed,
    Reset,
    ValueChange,
)
from compneurovis.core.selections import selection_after_click
from compneurovis.core.selections import SelectionSpec
from compneurovis.backends.neuron.geometry import build_morphology_geometry
from compneurovis.backends.neuron.section_names import section_lookup
from compneurovis.backends.interaction import (
    BackendInteractionContext,
    _selection_ids_from_internal,
)

DISPLAY_FIELD_ID = "segment_display"
HISTORY_FIELD_ID = "segment_history"


@dataclass(frozen=True)
class SegmentSamplingConfig:
    """Backend sampling for one per-segment NEURON scalar.

    This is a low-level producer configuration, not view or selection state.
    Source-authored morphology widgets use ordinary field bindings instead.
    """

    ref_of: Callable[[Any], Any]  # segment -> NEURON pointer ref, e.g. seg._ref_v
    unit: str | None = None


class NeuronBackend(CompartmentHistoryMixin, BackendBase, ABC):
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
        segment_sampling: SegmentSamplingConfig | None = None,
        geometry_required: bool = False,
        history_enabled: bool = False,
        title: str = "CompNeuroVis",
    ):
        super().__init__()
        self.dt = dt
        self.v_init = v_init
        self.max_samples = max_samples
        self.display_dt = display_dt
        self.history_capture_mode = HistoryCaptureMode(history_capture_mode)
        self._segment_sampling = segment_sampling
        self._geometry_required = bool(geometry_required or segment_sampling is not None)
        self._history_enabled = bool(history_enabled)
        self.title = title
        self.sections = None
        self._sections_by_name: dict[str, Any] | None = None
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
        self._selection_specs: dict[str, SelectionSpec] = {}
        self._active_selection_id: str | None = None
        self._last_time_value: float | None = None
        self._last_display_values: np.ndarray | None = None
        self._series_segment_ids: list[str] = []
        self._series_history_times: list[float] = []
        self._series_history_values_by_id: dict[str, list[float]] = {}
        self._series_refs_key: tuple[str, ...] | None = None
        self._series_refs = None
        self._series_vector = None
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

    def _require_segment_sampling(self) -> SegmentSamplingConfig:
        if self._segment_sampling is None:
            raise RuntimeError(
                "No low-level segment sampler is configured for this backend."
            )
        return self._segment_sampling

    def display_unit(self) -> str | None:
        return (
            self._segment_sampling.unit
            if self._segment_sampling is not None
            else None
        )

    def history_unit(self) -> str | None:
        return self.display_unit()

    def selection_id(self) -> str | None:
        if self._active_selection_id is not None:
            return self._active_selection_id
        if len(self._selection_specs) == 1:
            return next(iter(self._selection_specs))
        return None

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

    def should_capture_series_on_click(self, entity_id: str, context) -> bool:
        del entity_id, context
        return True

    def record(self, name: str, ref: Any) -> None:
        """Register one NEURON variable ref for batched PtrVector sampling."""

        self.record_many((name,), (ref,))

    def record_many(self, names: Sequence[str], refs: Sequence[Any]) -> None:
        """Register NEURON variable refs for sampling once per fadvance step."""

        if len(names) != len(refs):
            raise ValueError(
                "NeuronBackend record_many names and refs must have the same length"
            )
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

    def on_recorded_samples(
        self, times: np.ndarray, values: dict[str, np.ndarray]
    ) -> None:
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

        self._recorded_names.clear()
        self._recorded_refs.clear()
        self._recorded_ptrs = None
        self._recorded_vector = None
        self._invalidate_series_sampler()
        self.sections = self.build_sections()
        self._runtime_handles = self.setup_model(self.sections)

        if self._geometry_required:
            self.geometry = build_morphology_geometry(self.sections)
            self._entity_index_by_id = {
                entity_id: index
                for index, entity_id in enumerate(self.geometry.entity_ids)
            }
        else:
            self.geometry = None
            self._entity_index_by_id = {}

        if self._segment_sampling is not None:
            self._prepare_recorders()

        h.dt = self.dt
        h.finitialize(self.v_init)

        if self._segment_sampling is None:
            self._last_time_value = float(h.t)
            self._last_display_values = None
            self._clear_series_history()
            return float(h.t), None

        time_value, display_values = self._sample()
        self._last_time_value = float(time_value)
        self._last_display_values = np.asarray(display_values, dtype=np.float32)
        if self._history_enabled:
            self._initialize_series_history(time_value, display_values)
        else:
            self._clear_series_history()
        return time_value, display_values

    def build_startup_data(self) -> StartupData:
        """Build NEURON model and return simulator data. Sources add views/panels."""

        self._initialize_model()
        geometry_specs = (
            () if self.geometry is None else (self.geometry.to_spec(),)
        )
        if self._segment_sampling is None:
            return StartupData(geometries=geometry_specs, title=self.title)
        display_field = FieldSpec(
            id=self.display_field_id(),
            initial_values=np.asarray(self._last_display_values, dtype=np.float32),
            dims=("segment",),
            coords={"segment": np.asarray(self.geometry.entity_ids)},
            unit=self.display_unit(),
        )
        fields: list[FieldSpec] = [display_field]
        if self._history_enabled:
            series_segment_ids, series_times, series_values = (
                self._series_field_snapshot()
            )
            history_unit = (
                self.display_unit()
                if self.history_unit() is None
                else self.history_unit()
            )
            fields.append(
                FieldSpec(
                    id=self.history_field_id(),
                    initial_values=np.asarray(series_values, dtype=np.float32),
                    dims=("segment", "time"),
                    coords={
                        "segment": np.asarray(series_segment_ids),
                        "time": np.asarray(series_times, dtype=np.float32),
                    },
                    unit=history_unit,
                )
            )
        return StartupData(fields=tuple(fields), geometries=geometry_specs, title=self.title)

    def initialize(self, app_spec: AppSpec | None) -> None:
        if self._history_enabled:
            self._field_max_samples[self.history_field_id()] = (
                self._resolved_field_max_samples(
                    app_spec,
                    field_id=self.history_field_id(),
                    append_dim="time",
                )
            )
        self._selection_specs = {}
        self._active_selection_id = None
        if app_spec is not None and self.geometry is not None:
            for selection_ref, selection in app_spec.iter_selections():
                if str(selection.geometry_id) == self.geometry.id:
                    self._selection_specs[selection_ref.id] = selection

        known_entity_ids = set(self._entity_index_by_id)
        updates: dict[str, Any] = {
            selection_id: [
                entity_id
                for entity_id in selection.initial
                if entity_id in known_entity_ids
            ]
            for selection_id, selection in self._selection_specs.items()
        }
        for key, value in updates.items():
            self.values.set(key, value)
        if updates:
            self.emit_update(ValueChange(updates))
        if (
            self._history_enabled
            and self._segment_sampling is not None
            and self._last_time_value is not None
            and self._last_display_values is not None
        ):
            self._initialize_series_history(
                self._last_time_value, self._last_display_values
            )
            self.emit_update(self._series_field_replace())

    def _prepare_recorders(self):
        from neuron import h

        sections_by_name = self.sections_by_name()
        entity_sections = []
        entity_xlocs = []
        for entity_id, section_name, xloc in zip(
            self.geometry.entity_ids, self.geometry.section_names, self.geometry.xlocs
        ):
            del entity_id
            entity_sections.append(sections_by_name[section_name])
            entity_xlocs.append(float(xloc))

        ref_of = self._require_segment_sampling().ref_of
        self._segment_refs = h.PtrVector(len(entity_sections))
        self._segment_vector = h.Vector(len(entity_sections))
        for i, (section, xloc) in enumerate(zip(entity_sections, entity_xlocs)):
            self._segment_refs.pset(i, ref_of(section(xloc)))

    def _read_display_values(self) -> np.ndarray:
        self._segment_refs.gather(self._segment_vector)
        return np.asarray(self._segment_vector.as_numpy(), dtype=np.float32).copy()

    def _invalidate_series_sampler(self) -> None:
        self._series_refs_key = None
        self._series_refs = None
        self._series_vector = None

    def _rebuild_series_sampler(self) -> None:
        from neuron import h

        key = tuple(self._series_segment_ids)
        if key == self._series_refs_key:
            return
        self._series_refs_key = key
        if not key:
            self._series_refs = None
            self._series_vector = None
            return
        ref_of = self._require_segment_sampling().ref_of
        sections_by_name = self.sections_by_name()
        self._series_refs = h.PtrVector(len(key))
        self._series_vector = h.Vector(len(key))
        for ptr_index, entity_id in enumerate(key):
            entity_index = self._entity_index_by_id[entity_id]
            section_name = str(self.geometry.section_names[entity_index])
            xloc = float(self.geometry.xlocs[entity_index])
            self._series_refs.pset(
                ptr_index, ref_of(sections_by_name[section_name](xloc))
            )

    def sections_by_name(self) -> dict[str, Any]:
        """Stable public section-name lookup for runtime data bindings."""
        if self._sections_by_name is None:
            if self.sections is None:
                raise RuntimeError("NEURON model has not been initialized")
            # Section topology is fixed for one backend lifetime. Building this
            # map is O(section count), so never repeat it per sample.
            self._sections_by_name = section_lookup(self.sections)
        return self._sections_by_name

    def _read_selected_series_values(self) -> np.ndarray:
        if not self._series_segment_ids:
            return np.empty((0,), dtype=np.float32)
        self._rebuild_series_sampler()
        self._series_refs.gather(self._series_vector)
        return np.asarray(self._series_vector.as_numpy(), dtype=np.float32).copy()

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
        return {
            name: float(values[index])
            for index, name in enumerate(self._recorded_names)
        }

    def _sample(self) -> tuple[float, np.ndarray]:
        from neuron import h

        return float(h.t), self._read_display_values()

    def _selected_entity_ids_from_values(
        self, selection_id: str | None = None
    ) -> list[str]:
        selection_id = self.selection_id() if selection_id is None else selection_id
        if selection_id is None:
            return []
        selected_entity_ids = self.values.get(selection_id)
        if selected_entity_ids is None:
            return []
        resolved: list[str] = []
        for value in _selection_ids_from_internal(selected_entity_ids):
            if value in self._entity_index_by_id and value not in resolved:
                resolved.append(value)
        return resolved

    def _preferred_series_entity_ids(self) -> list[str]:
        preferred: list[str] = []
        for selection_id in self._selection_specs:
            for entity_id in self._selected_entity_ids_from_values(selection_id):
                if entity_id not in preferred:
                    preferred.append(entity_id)
        return preferred

    def _emit_on_demand_display_and_series(
        self,
        times_array: np.ndarray,
        latest_display_values: np.ndarray,
        selected_series_values: np.ndarray | None,
    ) -> None:
        self._last_time_value = float(times_array[-1])
        self._last_display_values = np.asarray(latest_display_values, dtype=np.float32)

        self.emit_update(self._display_field_replace(self._last_display_values))

        if (
            self._history_enabled
            and selected_series_values is not None
            and self._series_segment_ids
        ):
            self._append_selected_series_history_values(
                selected_series_values, times_array.tolist()
            )
            self.emit_update(
                FieldAppend(
                    field_id=self.history_field_id(),
                    append_dim="time",
                    values=selected_series_values,
                    coord_values=times_array,
                    max_length=self._field_max_samples.get(
                        self.history_field_id(), self.max_samples
                    ),
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

    def _resolved_field_max_samples(
        self, app_spec: AppSpec | None, *, field_id: str, append_dim: str
    ) -> int:
        return resolved_field_max_samples(
            app_spec,
            field_id=field_id,
            append_dim=append_dim,
            default=self.max_samples,
            step=self.dt,
        )

    def _sample_step(self) -> Any:
        """Return per-step data after each fadvance call.

        Override to sample custom quantities. Whatever you return here is collected
        into a list and passed to _emit_batch() once per display update batch.
        The default returns the current morphology display values array.
        """
        if self._segment_sampling is None:
            return None
        return self._read_display_values()

    def _emit_batch(self, times_array: np.ndarray, steps: list[Any]) -> None:
        """Emit display and history field updates for one batch of fadvance steps.

        Override to emit custom fields. steps is a list of whatever _sample_step()
        returned — one entry per fadvance step in the batch.
        The default handles morphology voltage display and trace/full history.
        """
        self._last_time_value = float(times_array[-1])
        if self._segment_sampling is None:
            return
        self._last_display_values = np.asarray(steps[-1], dtype=np.float32)

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
                    max_length=self._field_max_samples.get(
                        self.history_field_id(), self.max_samples
                    ),
                )
            )
        else:
            if self._series_segment_ids:
                selected_indices = [
                    self._entity_index_by_id[entity_id]
                    for entity_id in self._series_segment_ids
                ]
                selected_values = np.stack(
                    [
                        np.asarray(step, dtype=np.float32)[selected_indices]
                        for step in steps
                    ],
                    axis=1,
                )
                self._append_selected_series_history_values(
                    selected_values, times_array.tolist()
                )
                self.emit_update(
                    FieldAppend(
                        field_id=self.history_field_id(),
                        append_dim="time",
                        values=selected_values,
                        coord_values=times_array,
                        max_length=self._field_max_samples.get(
                            self.history_field_id(), self.max_samples
                        ),
                    )
                )

    # -- runtime loop: a complete standalone tick with integration seams -------

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
        frame_dt = self.sim_ms_per_frame()
        t_target = self._current_sim_time() + frame_dt
        time_tolerance = max(
            1e-12,
            abs(frame_dt) * 1e-9,
            abs(t_target) * 1e-12,
        )
        while True:
            self._advance()
            t = self._current_sim_time()
            self._on_step(t)
            self._pending_times.append(t)
            self._pending_steps.append(self._sample_step())
            recorded = self._read_recorded_values()
            if recorded is not None:
                self._pending_recorded.append(recorded)
            if t >= t_target - time_tolerance:
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
                {
                    name: recorded_batch[index]
                    for index, name in enumerate(self._recorded_names)
                },
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
            self._reset_pending_output_buffers()
            if self._segment_sampling is None:
                self._last_time_value = float(h.t)
                self._clear_series_history()
                return
            time_value, display_values = self._sample()
            self._last_time_value = float(time_value)
            self._last_display_values = np.asarray(display_values, dtype=np.float32)
            if self._history_enabled:
                self._initialize_series_history(time_value, display_values)
            else:
                self._clear_series_history()
            self.emit_update(self._display_field_replace(display_values))
            if self._history_enabled:
                self.emit_update(self._series_field_replace())
        elif isinstance(command, ValueChange):
            self.values.apply(self, command.updates)
        elif isinstance(command, InvokeAction):
            self._dispatch_action(command.action_id, command.payload)
        elif isinstance(command, EntityClicked):
            entity_id = str(command.entity_id)
            selection_id = command.selection_id
            selection = self._selection_specs.get(selection_id)
            if selection is None:
                return
            self._active_selection_id = selection_id
            context = self._interaction_context()

            selection_before = tuple(
                self._selected_entity_ids_from_values(selection_id)
            )
            handled = self.on_entity_clicked(entity_id, context)
            selection_after = tuple(
                self._selected_entity_ids_from_values(selection_id)
            )
            if not handled and selection_after == selection_before:
                selected_entity_ids = selection_after_click(
                    selection_before,
                    entity_id,
                    multiple=selection.multiple,
                )
                self.values.set(selection_id, selected_entity_ids)

            update = {
                selection_id: list(
                    self._selected_entity_ids_from_values(selection_id)
                )
            }
            for key, value in update.items():
                self.values.set(key, value)
            self.emit_update(ValueChange(update))
            self._after_entity_selection_changed(entity_id, context)

            if (
                self._history_enabled
                and self.history_capture_mode == HistoryCaptureMode.ON_DEMAND
                and self.should_capture_series_on_click(entity_id, context)
            ):
                if self._capture_series_entity(entity_id, include_current_sample=True):
                    self.emit_update(self._series_field_replace())
        elif isinstance(command, KeyPressed):
            self.on_key_press(command.key, self._interaction_context())
