from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
import math
from typing import Any, Callable, Sequence

import numpy as np

from compneurovis.core.controls import ActionSpec, ControlSpec
from compneurovis.core.app_spec import AppSpec, ViewCatalog
from compneurovis.core.views import LinePlotViewSpec
from compneurovis.backends import BackendBase, HistoryCaptureMode
from compneurovis.core.messages import BindingValuePatch, EntityClicked, FieldAppend, FieldReplace, InvokeAction, KeyPressed, Reset, SetControl, Status
from compneurovis.backends.neuron.app_spec import NeuronAppSpecBuilder


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
    label: str | None = None


class BackendInteractionContext:
    def __init__(self, backend: "NeuronBackend"):
        self.backend = backend

    def set_state(self, key: str, value: Any) -> None:
        self.backend._ui_state[key] = value
        self.backend.emit_update(BindingValuePatch({key: value}))

    def state(self, key: str, default: Any = None) -> Any:
        return self.backend._ui_state.get(key, default)

    @property
    def selected_entity_id(self) -> str | None:
        value = self.backend._ui_state.get("selected_entity_id")
        return str(value) if value is not None else None

    def entity_info(self, entity_id: str | None = None) -> dict[str, Any] | None:
        current_id = entity_id or self.selected_entity_id
        if current_id is None or self.backend.geometry is None:
            return None
        try:
            return self.backend.geometry.entity_info(current_id)
        except KeyError:
            return None

    def show_status(self, message: str, timeout_ms: int | None = None) -> None:
        self.backend.emit_update(Status(message, timeout_ms))

    def clear_status(self) -> None:
        self.backend.emit_update(Status("", 0))

    def invoke_action(self, action_id: str, payload: dict[str, Any] | None = None) -> None:
        self.backend._dispatch_action(action_id, payload or {})


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
        title: str = "CompNeuroVis",
    ):
        super().__init__()
        self.dt = dt
        self.v_init = v_init
        self.max_samples = max_samples
        self.display_dt = display_dt
        self.history_capture_mode = HistoryCaptureMode(history_capture_mode)
        self._display = display
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
        self._ui_state: dict[str, Any] = {}
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

    @abstractmethod
    def build_sections(self):
        """Return the NEURON sections that define the model morphology."""

        pass

    def setup_model(self, sections):
        """Insert mechanisms, stimuli, or recorders after sections are created."""

        return None

    def control_specs(self) -> dict[str, ControlSpec]:
        return {}

    def action_specs(self) -> dict[str, ActionSpec]:
        return {}

    def control_order(self) -> tuple[str, ...] | None:
        return None

    def action_order(self) -> tuple[str, ...] | None:
        return None

    def _default_action_specs(self) -> dict[str, ActionSpec]:
        return {
            "reset": ActionSpec("reset", "Reset", shortcuts=("Space",)),
        }

    def _resolved_action_specs(self) -> dict[str, ActionSpec]:
        actions = dict(self.action_specs())
        for action_id, action in self._default_action_specs().items():
            actions.setdefault(action_id, action)
        return actions

    def _resolved_action_order(self, actions: dict[str, ActionSpec]) -> tuple[str, ...] | None:
        action_order = self.action_order()
        if action_order is not None:
            return action_order
        return tuple(actions.keys()) if actions else None

    def trace_view_updates(self) -> dict[str, Any]:
        return {}

    def display_field_id(self) -> str:
        return NeuronAppSpecBuilder.DISPLAY_FIELD_ID

    def history_field_id(self) -> str:
        return NeuronAppSpecBuilder.HISTORY_FIELD_ID

    def _require_display(self) -> DisplayConfig:
        if self._display is None:
            raise RuntimeError(
                "No display variable configured. Declare the per-segment scalar the "
                "morphology/selection-trace shows via the attach source's .display(...)."
            )
        return self._display

    def display_unit(self) -> str | None:
        return self._display.unit if self._display is not None else None

    def history_unit(self) -> str | None:
        return self.display_unit()

    def morphology_color_map(self) -> str:
        return self._display.color_map if self._display is not None else "scalar"

    def morphology_color_limits(self) -> tuple[float, float] | None:
        return self._display.color_limits if self._display is not None else None

    def morphology_color_norm(self) -> str:
        return self._display.color_norm if self._display is not None else "auto"

    def trace_title(self) -> str:
        return "Trace"

    def trace_y_label(self) -> str:
        return "Value"

    def trace_y_unit(self) -> str:
        return self.history_unit() or ""

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

    def build_app_spec(self, *, geometry, display_values: np.ndarray, time_value: float) -> AppSpec:
        """Build the initial AppSpec from sampled values and morphology geometry."""

        controls = self.control_specs()
        actions = self._resolved_action_specs()
        trace_segment_ids, trace_times, trace_values = self._trace_field_snapshot()
        app_spec = NeuronAppSpecBuilder.build_app_spec(
            geometry=geometry,
            display_values=display_values,
            trace_values=trace_values,
            trace_segment_ids=trace_segment_ids,
            trace_times=trace_times,
            display_field_id=self.display_field_id(),
            history_field_id=self.history_field_id(),
            display_unit=self.display_unit(),
            history_unit=self.history_unit(),
            morphology_color_map=self.morphology_color_map(),
            morphology_color_limits=self.morphology_color_limits(),
            morphology_color_norm=self.morphology_color_norm(),
            trace_title=self.trace_title(),
            trace_y_label=self.trace_y_label(),
            trace_y_unit=self.trace_y_unit(),
            controls=controls,
            actions=actions,
            title=self.title,
            control_ids=self.control_order(),
            action_ids=self._resolved_action_order(actions),
        )
        trace_updates = self.trace_view_updates()
        if trace_updates:
            views = dict(app_spec.view_catalog.views)
            views["trace"] = replace(views["trace"], **trace_updates)
            app_spec = AppSpec(
                data=app_spec.data,
                view_catalog=ViewCatalog(
                    views=views,
                    operators=app_spec.view_catalog.operators,
                ),
                interactions=app_spec.interactions,
                layout_catalog=app_spec.layout_catalog,
                metadata=app_spec.metadata,
            )
        return app_spec

    def _initialize_model(self) -> tuple[float, np.ndarray]:
        """Build NEURON model, run finitialize, return (time, display_values)."""

        from neuron import h

        self.sections = self.build_sections()
        self._runtime_handles = self.setup_model(self.sections)
        self.geometry = NeuronAppSpecBuilder.build_morphology_geometry(self.sections)
        self._entity_index_by_id = {entity_id: index for index, entity_id in enumerate(self.geometry.entity_ids)}
        self._recorded_names.clear()
        self._recorded_refs.clear()
        self._recorded_ptrs = None
        self._recorded_vector = None
        self._trace_refs_key = None
        self._trace_refs = None
        self._trace_vector = None
        self._prepare_recorders()
        h.dt = self.dt
        h.finitialize(self.v_init)
        time_value, display_values = self._sample()
        self._initialize_trace_history(time_value, display_values)
        return time_value, display_values

    def build_startup_data(self) -> AppSpec:
        """Build NEURON model and return a data-only AppSpec (no views or panels)."""

        time_value, display_values = self._initialize_model()
        trace_segment_ids, trace_times, trace_values = self._trace_field_snapshot()
        return NeuronAppSpecBuilder.build_data_app_spec(
            geometry=self.geometry,
            display_values=display_values,
            trace_values=trace_values,
            trace_segment_ids=trace_segment_ids,
            trace_times=trace_times,
            display_field_id=self.display_field_id(),
            history_field_id=self.history_field_id(),
            display_unit=self.display_unit(),
            history_unit=self.history_unit(),
            title=self.title,
        )

    def build_startup_app_spec(self) -> AppSpec:
        """Build the NEURON model, sample it once, and return the initial AppSpec."""

        time_value, display_values = self._initialize_model()
        return self.build_app_spec(
            geometry=self.geometry,
            display_values=display_values,
            time_value=time_value,
        )

    def initialize(self, app_spec: AppSpec) -> None:
        self._field_max_samples[self.history_field_id()] = self._resolved_field_max_samples(
            app_spec,
            field_id=self.history_field_id(),
            append_dim="time",
        )
        self._ui_state = {}
        if self.geometry is not None and self.geometry.entity_ids:
            initial_entity_id = self.geometry.entity_ids[0]
            self._ui_state["selected_entity_id"] = initial_entity_id
            self.emit_update(BindingValuePatch({
                "selected_entity_id": initial_entity_id,
                "selected_entity_label": self.geometry.label_for(initial_entity_id),
            }))

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

    def _preferred_trace_entity_ids(self) -> list[str]:
        preferred: list[str] = []

        selected_trace_ids = self._ui_state.get("selected_trace_entity_ids")
        if selected_trace_ids is not None:
            for value in np.asarray(selected_trace_ids).astype(str).tolist():
                if value in self._entity_index_by_id and value not in preferred:
                    preferred.append(value)

        selected_entity_id = self._ui_state.get("selected_entity_id")
        if selected_entity_id is not None:
            value = str(selected_entity_id)
            if value in self._entity_index_by_id and value not in preferred:
                preferred.append(value)

        if not preferred and self.geometry.entity_ids:
            preferred.append(self.geometry.entity_ids[0])
        return preferred

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

        if selected_trace_values is not None and self._trace_segment_ids:
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

    def _resolved_field_max_samples(self, app_spec: AppSpec, *, field_id: str, append_dim: str) -> int:
        required = int(self.max_samples)
        if self.dt <= 0:
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

    def tick(self) -> None:
        """Update the simulation and emit incremental frontend updates."""

        from neuron import h

        if (
            self.history_capture_mode == HistoryCaptureMode.ON_DEMAND
            and type(self)._sample_step is NeuronBackend._sample_step
            and type(self)._emit_batch is NeuronBackend._emit_batch
        ):
            t_target = float(h.t) + self.sim_ms_per_frame()
            selected_trace_frames: list[np.ndarray] = []
            recorded_frames: list[np.ndarray] = []
            times: list[float] = []
            while True:
                h.fadvance()
                times.append(float(h.t))
                if self._trace_segment_ids:
                    selected_trace_frames.append(self._read_selected_trace_values())
                recorded = self._read_recorded_values()
                if recorded is not None:
                    recorded_frames.append(recorded)
                if float(h.t) >= t_target:
                    break

            times_array = np.asarray(times, dtype=np.float32)
            selected_trace_values = (
                np.stack(selected_trace_frames, axis=1).astype(np.float32)
                if selected_trace_frames
                else None
            )
            self._emit_on_demand_display_and_trace(
                times_array,
                self._read_display_values(),
                selected_trace_values,
            )

            if recorded_frames:
                recorded_batch = np.stack(recorded_frames, axis=1)
                self.on_recorded_samples(
                    times_array,
                    {name: recorded_batch[index] for index, name in enumerate(self._recorded_names)},
                )
            return

        t_target = float(h.t) + self.sim_ms_per_frame()
        steps: list[Any] = []
        recorded_frames: list[np.ndarray] = []
        times: list[float] = []
        while True:
            h.fadvance()
            times.append(float(h.t))
            steps.append(self._sample_step())
            recorded = self._read_recorded_values()
            if recorded is not None:
                recorded_frames.append(recorded)
            if float(h.t) >= t_target:
                break

        times_array = np.asarray(times, dtype=np.float32)
        self._emit_batch(times_array, steps)

        if recorded_frames:
            recorded_batch = np.stack(recorded_frames, axis=1)
            self.on_recorded_samples(
                times_array,
                {name: recorded_batch[index] for index, name in enumerate(self._recorded_names)},
            )

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
            self._initialize_trace_history(time_value, display_values)
            self.emit_update(
                self._display_field_replace(display_values)
            )
            self.emit_update(self._trace_field_replace())
        elif isinstance(command, SetControl):
            self.apply_control(command.control_id, command.value)
        elif isinstance(command, InvokeAction):
            self._dispatch_action(command.action_id, command.payload)
        elif isinstance(command, EntityClicked):
            self._ui_state["selected_entity_id"] = command.entity_id
            context = self._interaction_context()
            if self.history_capture_mode == HistoryCaptureMode.ON_DEMAND and self.should_capture_trace_on_click(command.entity_id, context):
                if self._capture_trace_entity(command.entity_id, include_current_sample=True):
                    self.emit_update(self._trace_field_replace())
            self.on_entity_clicked(command.entity_id, context)
        elif isinstance(command, KeyPressed):
            self.on_key_press(command.key, self._interaction_context())
