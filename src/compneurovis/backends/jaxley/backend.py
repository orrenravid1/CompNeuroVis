from __future__ import annotations

from abc import ABC, abstractmethod
import math
import time
from typing import TYPE_CHECKING, Any, Iterable

import numpy as np

from compneurovis.backends.jaxley.geometry import build_morphology_geometry
from compneurovis.core._perf import perf_log
from compneurovis.core.controls import ActionSpec
from compneurovis.core.app_spec import AppSpec
from compneurovis.core.field import FieldSpec
from compneurovis.core.views import LinePlotViewSpec
from compneurovis.inline.app_compiler import StartupData
from compneurovis.backends import BackendBase, HistoryCaptureMode
from compneurovis.backends.interaction import (
    BackendInteractionContext,
    SELECTED_ENTITY_ID_KEY,
    SELECTED_ENTITY_IDS_KEY,
    _selection_ids_from_internal,
    _selection_to_internal,
)
from compneurovis.core.messages import EntityClicked, FieldAppend, FieldReplace, InvokeAction, KeyPressed, Reset, ValueChange

if TYPE_CHECKING:  # pragma: no cover - optional dependency typing only
    import jaxley as jx

DISPLAY_FIELD_ID = "segment_display"
HISTORY_FIELD_ID = "segment_history"
TRACE_FIELD_ID = HISTORY_FIELD_ID


class JaxleyBackend(BackendBase, ABC):
    """Base class for live Jaxley-backed CompNeuroVis sessions."""

    HISTORY_CAPTURE_ON_DEMAND = HistoryCaptureMode.ON_DEMAND
    HISTORY_CAPTURE_FULL = HistoryCaptureMode.FULL

    def __init__(
        self,
        *,
        dt: float = 0.1,
        v_init: float = -70.0,
        max_samples: int = 1000,
        display_dt: float | None = 0.1,
        flush_dt: float | None = None,
        history_capture_mode: HistoryCaptureMode | str = HistoryCaptureMode.ON_DEMAND,
        history_enabled: bool = False,
        selected: Any = None,
        select_multiple: bool = False,
        title: str = "CompNeuroVis",
    ):
        super().__init__()
        self.dt = dt
        self.v_init = v_init
        self.max_samples = max_samples
        self.display_dt = display_dt
        self._flush_dt = float(flush_dt) if flush_dt else 0.0
        self.history_capture_mode = HistoryCaptureMode(history_capture_mode)
        self._history_enabled = bool(history_enabled)
        self._selected_entity_ids = tuple(_selection_to_internal(selected, select_multiple=select_multiple))
        self._select_multiple = bool(select_multiple)
        self.title = title
        self.cells = None
        self.network = None
        self.geometry = None
        self._runtime_handles = None
        self._field_max_samples: dict[str, int] = {}
        self._init_fn = None
        self._step_fn = None
        self._state = None
        self._all_params = None
        self._externals: dict[str, np.ndarray] = {}
        self._external_inds: dict[str, np.ndarray] = {}
        self._rec_indices: np.ndarray | None = None
        self._rec_states: tuple[str, ...] = ()
        self._time = 0.0
        self._step_index = 0
        self._entity_index_by_id: dict[str, int] = {}
        self._last_display_values: np.ndarray | None = None
        self._last_voltage_values: np.ndarray | None = None
        self._trace_segment_ids: list[str] = []
        self._tick_count = 0
        self._last_tick_log_s = 0.0
        self._pending_times: list[float] = []
        self._pending_steps: list[Any] = []
        self._last_flush_t: float | None = None
        self._trace_history_times: list[float] = []
        self._trace_history_values_by_id: dict[str, list[float]] = {}

    @abstractmethod
    def build_cells(self) -> Iterable["jx.Cell"] | "jx.Cell":
        """Return one Jaxley cell or an iterable of cells for the backend."""

        pass

    def build_network(self, cells: list["jx.Cell"]):
        """Build the Jaxley network from the returned cells."""

        import jax  # noqa: F401
        import jaxley as jx

        return jx.Network(cells)

    def setup_model(self, network, cells):
        """Configure channels, stimuli, recordings, or other runtime setup."""

        del network, cells
        return None

    def cell_names(self, cells: list["jx.Cell"]) -> list[str]:
        return [str(getattr(cell, "meta_name", f"cell_{i}")) for i, cell in enumerate(cells)]

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

    def display_unit(self) -> str | None:
        return "mV"

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

    def should_capture_trace_on_click(self, entity_id: str, context) -> bool:
        del entity_id, context
        return True

    def _initialize_model(self) -> np.ndarray:
        """Build Jaxley model, compile step function, return initial display_values."""

        perf_log(
            "jaxley_backend",
            "initialize_start",
            title=self.title,
            dt=self.dt,
            display_dt=self.display_dt,
            flush_dt=self._flush_dt,
            history_enabled=self._history_enabled,
            history_capture_mode=str(self.history_capture_mode.value),
        )
        print(f"[{self.title}] Importing JAX and Jaxley...")
        from jax import config as _jax_config
        _jax_config.update("jax_enable_x64", True)
        import jax  # noqa: F401
        import jaxley as jx
        from jaxley.integrate import build_init_and_step_fn

        perf_log("jaxley_backend", "initialize_imports_ready", title=self.title)
        print(f"[{self.title}] Building cells...")
        built = self.build_cells()
        self.cells = [built] if isinstance(built, jx.Cell) else list(built)

        perf_log("jaxley_backend", "initialize_cells_ready", title=self.title, cell_count=len(self.cells))
        print(f"[{self.title}] Building network ({len(self.cells)} cell(s))...")
        self.network = self.build_network(self.cells)

        perf_log("jaxley_backend", "initialize_network_ready", title=self.title)
        print(f"[{self.title}] Setting up model...")
        self._runtime_handles = self.setup_model(self.network, self.cells)

        perf_log("jaxley_backend", "initialize_setup_ready", title=self.title)
        print(f"[{self.title}] Initializing gating variables at v_init={self.v_init} mV...")
        self.network.set("v", self.v_init)
        self.network.init_states()

        perf_log("jaxley_backend", "initialize_states_ready", title=self.title)
        print(f"[{self.title}] Converting to JAX format...")
        self.network.delete_recordings()
        self.network.record("v", verbose=False)
        self.network.to_jax()
        params = self.network.get_parameters()

        perf_log("jaxley_backend", "initialize_to_jax_ready", title=self.title)
        print(f"[{self.title}] Tracing step function...")
        self._init_fn, self._step_fn = build_init_and_step_fn(self.network)

        perf_log("jaxley_backend", "initialize_step_fn_ready", title=self.title)
        print(f"[{self.title}] Compiling (first run may take a moment)...")
        compile_start_s = time.monotonic()
        self._state, self._all_params = self._init_fn(params, delta_t=self.dt)
        perf_log(
            "jaxley_backend",
            "initialize_init_fn_complete",
            title=self.title,
            duration_ms=round((time.monotonic() - compile_start_s) * 1000.0, 3),
        )

        self._externals = {key: np.asarray(value) for key, value in self.network.externals.copy().items()}
        self._external_inds = {key: np.asarray(value) for key, value in self.network.external_inds.copy().items()}
        self._rec_indices = np.asarray(self.network.recordings.rec_index.to_numpy(), dtype=np.int32)
        self._rec_states = tuple(str(value) for value in self.network.recordings.state.to_numpy().tolist())
        self._time = 0.0
        self._step_index = 0

        perf_log(
            "jaxley_backend",
            "initialize_runtime_arrays_ready",
            title=self.title,
            external_keys=tuple(self._externals.keys()),
            recording_count=0 if self._rec_indices is None else int(len(self._rec_indices)),
        )
        print(f"[{self.title}] Building morphology geometry...")
        self.geometry = build_morphology_geometry(
            self.network.nodes,
            xyzr=self.network.xyzr,
            cell_names=self.cell_names(self.cells),
        )
        display_values = self._read_display_values()
        self._entity_index_by_id = {entity_id: index for index, entity_id in enumerate(self.geometry.entity_ids)}
        self._last_display_values = np.asarray(display_values, dtype=np.float32)
        self._last_voltage_values = self._last_display_values
        if self._history_enabled:
            self._initialize_trace_history(self._time, display_values)
        else:
            self._clear_trace_history()
        perf_log(
            "jaxley_backend",
            "initialize_ready",
            title=self.title,
            segment_count=len(self.geometry.entity_ids),
            initial_time_ms=self._time,
        )
        print(f"[{self.title}] Ready.")
        return display_values

    def build_startup_data(self) -> StartupData:
        """Build Jaxley model and return simulator data. Sources add views/panels."""

        display_values = self._initialize_model()
        display_field = FieldSpec(
            id=self.display_field_id(),
            initial_values=np.asarray(display_values, dtype=np.float32),
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
        selected_entity_ids = self._initial_selected_entity_ids()
        update = {SELECTED_ENTITY_IDS_KEY: selected_entity_ids}
        if selected_entity_ids:
            selected_entity_id = selected_entity_ids[0]
            update[SELECTED_ENTITY_ID_KEY] = selected_entity_id
            update["selected_entity_label"] = self.geometry.label_for(selected_entity_id)
        for key, value in update.items():
            self.values.set(key, value)
        self.emit_update(ValueChange(update))


    def _initial_selected_entity_ids(self) -> list[str]:
        if self.geometry is None:
            return []
        known = set(self.geometry.entity_ids)
        return [entity_id for entity_id in self._selected_entity_ids if entity_id in known]

    def _clicked_selection(self, entity_id: str) -> list[str]:
        entity_id = str(entity_id)
        if not self._select_multiple:
            return [entity_id]
        current = _selection_ids_from_internal(self.values.get(SELECTED_ENTITY_IDS_KEY))
        selected = [value for value in current if value != entity_id]
        if len(selected) == len(current):
            selected.append(entity_id)
        return selected

    def _read_display_values(self) -> np.ndarray:
        if self._rec_indices is None:
            raise RuntimeError("JaxleyBackend recordings are not initialized")
        values = [
            np.asarray(self._state[state_name])[int(index)]
            for state_name, index in zip(self._rec_states, self._rec_indices)
        ]
        return np.asarray(values, dtype=np.float32)

    def _read_voltage(self) -> np.ndarray:
        return self._read_display_values()

    def _initialize_trace_history(self, time_value: float, display_values: np.ndarray) -> None:
        self._last_display_values = np.asarray(display_values, dtype=np.float32)
        self._last_voltage_values = self._last_display_values
        self._trace_history_times = [float(time_value)]
        self._trace_history_values_by_id = {}
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

    def _preferred_trace_entity_ids(self) -> list[str]:
        preferred: list[str] = []

        for value in _selection_ids_from_internal(self.values.get(SELECTED_ENTITY_IDS_KEY)):
            if value in self._entity_index_by_id and value not in preferred:
                preferred.append(value)


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
        self._trace_history_times.extend(float(time_value) for time_value in times)
        for entity_id in self._trace_segment_ids:
            index = self._entity_index_by_id[entity_id]
            self._trace_history_values_by_id[entity_id].extend(float(value) for value in batch_values[index])
        max_length = self._field_max_samples.get(self.history_field_id())
        if max_length is not None:
            self._trim_selected_trace_history(int(max_length))

    def sim_ms_per_frame(self) -> float:
        if self.display_dt is None:
            return float(self.dt)
        if self.display_dt <= 0:
            raise ValueError("JaxleyBackend display_dt must be positive or None")
        return float(self.display_dt)

    def idle_sleep(self) -> float:
        return 0.0

    def is_active(self) -> bool:
        return True

    def _reset_pending_output_buffers(self) -> None:
        self._pending_times = []
        self._pending_steps = []
        self._last_flush_t = float(self._time)

    def _resolved_field_max_samples(self, app_spec: AppSpec | None, *, field_id: str, append_dim: str) -> int:
        required = int(self.max_samples)
        if self.dt <= 0:
            return required
        # Standalone the backend initializes with app_spec=None (no views) and
        # uses its own max_samples; a source supplies views for a tighter buffer.
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

    def _externals_for_step(self, step_index: int) -> dict[str, np.ndarray]:
        externals: dict[str, np.ndarray] = {}
        for key, values in self._externals.items():
            if values.ndim == 0:
                externals[key] = values
            elif values.ndim == 1:
                externals[key] = values[step_index] if step_index < values.shape[0] else np.zeros_like(values[0])
            else:
                externals[key] = values[..., step_index] if step_index < values.shape[-1] else np.zeros_like(values[..., 0])
        return externals

    def _reinitialize_runtime(self, *, preserve_state: bool) -> None:
        if self.network is None or self._init_fn is None:
            return
        # Jaxley stores authoritative mutable parameters/states in DataFrames and copies
        # them into jaxnodes/jaxedges via to_jax(). Reset and live parameter updates must
        # resync from the DataFrame-backed model before rebuilding all_params/all_states.
        if not preserve_state:
            self.network.set("v", self.v_init)
            self.network.init_states()
        self.network.to_jax()
        params = self.network.get_parameters()
        current_state = self._state if preserve_state else None
        self._state, self._all_params = self._init_fn(
            params,
            all_states=current_state,
            delta_t=self.dt,
        )

    def refresh_runtime_parameters(self, *, preserve_state: bool = True) -> None:
        self._reinitialize_runtime(preserve_state=preserve_state)

    def refresh_runtime_externals(self) -> None:
        if self.network is None:
            return
        self._externals = {key: np.asarray(value) for key, value in self.network.externals.copy().items()}
        self._external_inds = {key: np.asarray(value) for key, value in self.network.external_inds.copy().items()}

    def _read_state(self, state_name: str) -> np.ndarray:
        """Read any Jaxley state variable at the display compartment indices.

        state_name is the internal Jaxley state key, e.g. 'HH_m', 'HH_n', 'HH_h'.
        Returns a float32 array with one value per morphology display entity,
        in the same order as the morphology coloring.
        """
        return np.asarray(self._state[state_name])[self._rec_indices].astype(np.float32)

    def _sample_step(self) -> Any:
        """Return per-step data after each simulation step.

        Override to sample additional channel states alongside voltage. Whatever
        you return here is collected into a list and passed to _emit_batch() once
        per display update batch. Use _read_state() to read any channel variable
        at the display compartment indices. The default returns the voltage array.
        """
        return self._read_display_values()

    def _emit_batch(self, times_array: np.ndarray, steps: list[Any]) -> None:
        """Emit display and history field updates for one batch of simulation steps.

        Override to emit custom fields. steps is a list of whatever _sample_step()
        returned — one entry per simulation step in the batch.
        The default handles morphology voltage display and trace/full history.
        """
        batch_values = np.stack(steps, axis=1)
        self._last_display_values = np.asarray(steps[-1], dtype=np.float32)
        self._last_voltage_values = self._last_display_values

        self.emit_update(self._display_field_replace(self._last_display_values))

        if not self._history_enabled:
            return

        if self.history_capture_mode == HistoryCaptureMode.FULL:
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
            self._append_selected_trace_history(batch_values, times_array.tolist())
            if self._trace_segment_ids:
                indices = [self._entity_index_by_id[entity_id] for entity_id in self._trace_segment_ids]
                self.emit_update(
                    FieldAppend(
                        field_id=self.history_field_id(),
                        append_dim="time",
                        values=batch_values[indices, :],
                        coord_values=times_array,
                        max_length=self._field_max_samples.get(self.history_field_id(), self.max_samples),
                    )
                )

    def tick(self) -> None:
        """Advance one display frame and flush buffered updates when due."""

        tick_start_s = time.monotonic()
        start_time = float(self._time)
        start_step_index = int(self._step_index)
        if self._last_flush_t is None:
            self._last_flush_t = start_time
        sim_ms_per_frame = self.sim_ms_per_frame()
        t_target = self._time + sim_ms_per_frame
        expected_steps = max(1, int(math.ceil(sim_ms_per_frame / float(self.dt)))) if self.dt > 0 else 0
        self._tick_count += 1
        if self._tick_count == 1:
            perf_log(
                "jaxley_backend",
                "tick_start",
                title=self.title,
                tick_count=self._tick_count,
                sim_time_ms=round(start_time, 6),
                target_time_ms=round(float(t_target), 6),
                dt=self.dt,
                display_dt=self.display_dt,
                flush_dt=self._flush_dt,
                expected_steps=expected_steps,
            )

        steps: list[Any] = []
        times: list[float] = []
        last_progress_log_s = tick_start_s
        while True:
            externals = self._externals_for_step(self._step_index)
            self._state = self._step_fn(
                self._state,
                self._all_params,
                externals,
                self._external_inds,
                delta_t=self.dt,
            )
            self._step_index += 1
            self._time += float(self.dt)
            times.append(self._time)
            steps.append(self._sample_step())
            progress_now_s = time.monotonic()
            if progress_now_s - last_progress_log_s >= 1.0:
                last_progress_log_s = progress_now_s
                perf_log(
                    "jaxley_backend",
                    "tick_progress",
                    title=self.title,
                    tick_count=self._tick_count,
                    elapsed_ms=round((progress_now_s - tick_start_s) * 1000.0, 3),
                    sim_time_ms=round(float(self._time), 6),
                    steps=len(steps),
                    expected_steps=expected_steps,
                    step_index=int(self._step_index),
                )
            if self._time >= t_target:
                break

        self._pending_times.extend(times)
        self._pending_steps.extend(steps)

        emit_start_s = time.monotonic()
        emitted = False
        if (self._time - self._last_flush_t) >= self._flush_dt - 1e-9:
            emitted = self._flush_pending()
        now_s = time.monotonic()
        duration_ms = (now_s - tick_start_s) * 1000.0
        emit_ms = (now_s - emit_start_s) * 1000.0 if emitted else 0.0
        should_log = self._tick_count == 1 or duration_ms >= 50.0 or now_s - self._last_tick_log_s >= 1.0
        if should_log:
            self._last_tick_log_s = now_s
            perf_log(
                "jaxley_backend",
                "tick_complete",
                title=self.title,
                tick_count=self._tick_count,
                duration_ms=round(duration_ms, 3),
                emit_ms=round(emit_ms, 3),
                emitted=emitted,
                pending_steps=len(self._pending_steps),
                sim_start_ms=round(start_time, 6),
                sim_end_ms=round(float(self._time), 6),
                sim_advanced_ms=round(float(self._time - start_time), 6),
                step_start_index=start_step_index,
                step_end_index=int(self._step_index),
                steps=len(steps),
                expected_steps=expected_steps,
                dt=self.dt,
                display_dt=self.display_dt,
                flush_dt=self._flush_dt,
            )

    def _flush_pending(self) -> bool:
        """Emit buffered display/history samples and reset the flush buffer."""
        if not self._pending_steps:
            return False
        times_array = np.asarray(self._pending_times, dtype=np.float32)
        self._emit_batch(times_array, self._pending_steps)
        self._pending_times = []
        self._pending_steps = []
        self._last_flush_t = float(self._time)
        return True

    def _interaction_context(self) -> BackendInteractionContext:
        return BackendInteractionContext(self)

    def _dispatch_action(self, action_id: str, payload: dict[str, Any]) -> bool:
        if self.on_action(action_id, payload, self._interaction_context()):
            return True
        return self.apply_action(action_id, payload)

    def handle(self, message) -> None:
        command = message.payload
        if isinstance(command, Reset):
            self._reinitialize_runtime(preserve_state=False)
            self._time = 0.0
            self._step_index = 0
            self._pending_times = []
            self._pending_steps = []
            self._last_flush_t = None
            display_values = self._read_display_values()
            self._last_display_values = np.asarray(display_values, dtype=np.float32)
            self._last_voltage_values = self._last_display_values
            if self._history_enabled:
                self._initialize_trace_history(self._time, display_values)
            else:
                self._clear_trace_history()
            self.emit_update(self._display_field_replace(display_values))
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
            selected_entity_id = str(command.entity_id)
            selected_entity_label = self.geometry.label_for(selected_entity_id) if self.geometry is not None else selected_entity_id
            update = {
                SELECTED_ENTITY_IDS_KEY: self._clicked_selection(selected_entity_id),
                SELECTED_ENTITY_ID_KEY: selected_entity_id,
                "selected_entity_label": selected_entity_label,
            }
            for key, value in update.items():
                self.values.set(key, value)
            self.emit_update(ValueChange(update))
            context = self._interaction_context()
            if (
                self._history_enabled
                and self.history_capture_mode == HistoryCaptureMode.ON_DEMAND
                and self.should_capture_trace_on_click(command.entity_id, context)
            ):
                if self._capture_trace_entity(command.entity_id, include_current_sample=True):
                    self.emit_update(self._trace_field_replace())
            self.on_entity_clicked(command.entity_id, context)
        elif isinstance(command, KeyPressed):
            self.on_key_press(command.key, self._interaction_context())




