from __future__ import annotations

from abc import ABC, abstractmethod
import math
import time
from typing import TYPE_CHECKING, Any, Iterable

import numpy as np

from compneurovis.backends.jaxley.geometry import build_morphology_geometry
from compneurovis.core.runtime.performance import perf_log
from compneurovis.core.app_spec import AppSpec
from compneurovis.core.field import FieldSpec
from compneurovis.backends.compartment import (
    CompartmentHistoryMixin,
    resolved_field_max_samples,
)
from compneurovis.backends.startup import StartupData
from compneurovis.backends import BackendBase, HistoryCaptureMode
from compneurovis.backends.interaction import (
    BackendInteractionContext,
    _selection_ids_from_internal,
)
from compneurovis.core.messages import (
    FieldAppend,
    Reset,
)
from compneurovis.core.selections import SelectionSpec

if TYPE_CHECKING:  # pragma: no cover - optional dependency typing only
    import jaxley as jx

DISPLAY_FIELD_ID = "segment_display"
HISTORY_FIELD_ID = "segment_history"


class JaxleyBackend(CompartmentHistoryMixin, BackendBase, ABC):
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
        jax_enable_x64: bool | None = None,
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
        self.jax_enable_x64 = jax_enable_x64
        self._selection_specs: dict[str, SelectionSpec] = {}
        self._active_selection_id: str | None = None
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
        self._display_indices: np.ndarray | None = None
        self._time = 0.0
        self._step_index = 0
        self._entity_index_by_id: dict[str, int] = {}
        self._last_display_values: np.ndarray | None = None
        self._series_segment_ids: list[str] = []
        self._tick_count = 0
        self._last_tick_log_s = 0.0
        self._pending_times: list[float] = []
        self._pending_steps: list[Any] = []
        self._last_flush_t: float | None = None
        self._series_history_times: list[float] = []
        self._series_history_values_by_id: dict[str, list[float]] = {}

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
        return [
            str(getattr(cell, "meta_name", f"cell_{i}")) for i, cell in enumerate(cells)
        ]

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

    def selection_id(self) -> str | None:
        if self._active_selection_id is not None:
            return self._active_selection_id
        if len(self._selection_specs) == 1:
            return next(iter(self._selection_specs))
        return None

    def apply_invoke(self, interaction_id: str, payload: dict[str, object]) -> bool:
        del interaction_id, payload
        return False

    def on_invoke(self, interaction_id: str, payload: dict[str, Any], context) -> bool:
        del interaction_id, payload, context
        return False

    def should_capture_series_on_click(self, entity_id: str, context) -> bool:
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
        if self.jax_enable_x64 is not None:
            from jax import config as _jax_config

            _jax_config.update("jax_enable_x64", bool(self.jax_enable_x64))
        import jax  # noqa: F401
        import jaxley as jx
        from jaxley.integrate import build_init_and_step_fn

        perf_log("jaxley_backend", "initialize_imports_ready", title=self.title)
        built = self.build_cells()
        self.cells = [built] if isinstance(built, jx.Cell) else list(built)

        perf_log(
            "jaxley_backend",
            "initialize_cells_ready",
            title=self.title,
            cell_count=len(self.cells),
        )
        self.network = self.build_network(self.cells)

        perf_log("jaxley_backend", "initialize_network_ready", title=self.title)
        self._runtime_handles = self.setup_model(self.network, self.cells)

        perf_log("jaxley_backend", "initialize_setup_ready", title=self.title)
        self.network.set("v", self.v_init)
        self.network.init_states()

        perf_log("jaxley_backend", "initialize_states_ready", title=self.title)
        self.network.to_jax()
        params = self.network.get_parameters()

        perf_log("jaxley_backend", "initialize_to_jax_ready", title=self.title)
        self._init_fn, self._step_fn = build_init_and_step_fn(self.network)

        perf_log("jaxley_backend", "initialize_step_fn_ready", title=self.title)
        compile_start_s = time.monotonic()
        self._state, self._all_params = self._init_fn(params, delta_t=self.dt)
        perf_log(
            "jaxley_backend",
            "initialize_init_fn_complete",
            title=self.title,
            duration_ms=round((time.monotonic() - compile_start_s) * 1000.0, 3),
        )

        self._externals = {
            key: np.asarray(value)
            for key, value in self.network.externals.copy().items()
        }
        self._external_inds = {
            key: np.asarray(value)
            for key, value in self.network.external_inds.copy().items()
        }
        ordered_nodes = self.network.nodes.sort_values("global_comp_index")
        self._display_indices = ordered_nodes[
            "global_comp_index"
        ].to_numpy(dtype=np.int32)
        self._time = 0.0
        self._step_index = 0

        perf_log(
            "jaxley_backend",
            "initialize_runtime_arrays_ready",
            title=self.title,
            external_keys=tuple(self._externals.keys()),
            display_compartment_count=0
            if self._display_indices is None
            else int(len(self._display_indices)),
        )
        self.geometry = build_morphology_geometry(
            self.network.nodes,
            xyzr=self.network.xyzr,
            cell_names=self.cell_names(self.cells),
        )
        display_values = self._read_display_values()
        self._entity_index_by_id = {
            entity_id: index for index, entity_id in enumerate(self.geometry.entity_ids)
        }
        self._last_display_values = np.asarray(display_values, dtype=np.float32)
        if self._history_enabled:
            self._initialize_series_history(self._time, display_values)
        else:
            self._clear_series_history()
        perf_log(
            "jaxley_backend",
            "initialize_ready",
            title=self.title,
            segment_count=len(self.geometry.entity_ids),
            initial_time_ms=self._time,
        )
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
        return StartupData(
            fields=tuple(fields), geometries=(self.geometry.to_spec(),), title=self.title
        )

    def initialize(self, app_spec: AppSpec | None) -> None:
        if self._history_enabled:
            self._field_max_samples[self.history_field_id()] = (
                self._resolved_field_max_samples(
                    app_spec,
                    field_id=self.history_field_id(),
                    append_dim="time",
                )
            )
        super().initialize(app_spec)
        if (
            self._history_enabled
            and self._last_display_values is not None
        ):
            self._initialize_series_history(self._time, self._last_display_values)
            self.emit_update(self._series_field_replace())

    def _read_display_values(self) -> np.ndarray:
        if self._display_indices is None:
            raise RuntimeError("JaxleyBackend display sampling is not initialized")
        return np.asarray(self._state["v"])[self._display_indices].astype(np.float32)

    def _preferred_series_entity_ids(self) -> list[str]:
        preferred: list[str] = []
        for selection_id in self._selection_specs:
            current = self.values.get(selection_id)
            for value in _selection_ids_from_internal(current):
                if value in self._entity_index_by_id and value not in preferred:
                    preferred.append(value)

        return preferred

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

    def _externals_for_step(self, step_index: int) -> dict[str, np.ndarray]:
        externals: dict[str, np.ndarray] = {}
        for key, values in self._externals.items():
            if values.ndim == 0:
                externals[key] = values
            elif values.ndim == 1:
                externals[key] = (
                    values[step_index]
                    if step_index < values.shape[0]
                    else np.zeros_like(values[0])
                )
            else:
                externals[key] = (
                    values[..., step_index]
                    if step_index < values.shape[-1]
                    else np.zeros_like(values[..., 0])
                )
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
        self._externals = {
            key: np.asarray(value)
            for key, value in self.network.externals.copy().items()
        }
        self._external_inds = {
            key: np.asarray(value)
            for key, value in self.network.external_inds.copy().items()
        }

    def _read_state(self, state_name: str) -> np.ndarray:
        """Read any Jaxley state variable at the display compartment indices.

        state_name is the internal Jaxley state key, e.g. 'HH_m', 'HH_n', 'HH_h'.
        Returns a float32 array with one value per morphology display entity,
        in the same order as the morphology coloring.
        """
        if self._display_indices is None:
            raise RuntimeError("JaxleyBackend display sampling is not initialized")
        return np.asarray(self._state[state_name])[self._display_indices].astype(
            np.float32
        )

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
                    max_length=self._field_max_samples.get(
                        self.history_field_id(), self.max_samples
                    ),
                )
            )
        else:
            self._append_selected_series_history(batch_values, times_array.tolist())
            if self._series_segment_ids:
                indices = [
                    self._entity_index_by_id[entity_id]
                    for entity_id in self._series_segment_ids
                ]
                self.emit_update(
                    FieldAppend(
                        field_id=self.history_field_id(),
                        append_dim="time",
                        values=batch_values[indices, :],
                        coord_values=times_array,
                        max_length=self._field_max_samples.get(
                            self.history_field_id(), self.max_samples
                        ),
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
        expected_steps = (
            max(1, int(math.ceil(sim_ms_per_frame / float(self.dt))))
            if self.dt > 0
            else 0
        )
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
        should_log = (
            self._tick_count == 1
            or duration_ms >= 50.0
            or now_s - self._last_tick_log_s >= 1.0
        )
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

    def _dispatch_invoke(self, interaction_id: str, payload: dict[str, Any]) -> bool:
        if self.on_invoke(interaction_id, payload, self._interaction_context()):
            return True
        return self.apply_invoke(interaction_id, payload)

    def handle_backend_message(self, message) -> None:
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
            if self._history_enabled:
                self._initialize_series_history(self._time, display_values)
            else:
                self._clear_series_history()
            self.emit_update(self._display_field_replace(display_values))
            if self._history_enabled:
                self.emit_update(self._series_field_replace())

    def after_click(self, event, context) -> None:
        interaction = self._click_specs[event.interaction_id]
        if interaction.result_kind != "entity":
            return
        entity_id = str(event.value)
        if (
            self._history_enabled
            and self.history_capture_mode == HistoryCaptureMode.ON_DEMAND
            and self.should_capture_series_on_click(entity_id, context)
            and self._capture_series_entity(entity_id, include_current_sample=True)
        ):
            self.emit_update(self._series_field_replace())
