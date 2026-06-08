from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import replace
import math
from typing import TYPE_CHECKING, Any, Iterable

import numpy as np

from compneurovis.backends.jaxley.app_spec import JaxleyAppSpecBuilder
from compneurovis.core.controls import ActionSpec, ControlSpec
from compneurovis.core.app_spec import AppSpec, ViewCatalog
from compneurovis.core.views import LinePlotViewSpec
from compneurovis.backends import BackendBase, HistoryCaptureMode
from compneurovis.core.messages import BindingValuePatch, EntityClicked, FieldAppend, FieldReplace, InvokeAction, KeyPressed, Reset, SetControl, Status

if TYPE_CHECKING:  # pragma: no cover - optional dependency typing only
    import jaxley as jx


class BackendInteractionContext:
    def __init__(self, backend: "JaxleyBackend"):
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
        history_capture_mode: HistoryCaptureMode | str = HistoryCaptureMode.ON_DEMAND,
        title: str = "CompNeuroVis",
    ):
        super().__init__()
        self.dt = dt
        self.v_init = v_init
        self.max_samples = max_samples
        self.display_dt = display_dt
        self.history_capture_mode = HistoryCaptureMode(history_capture_mode)
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
        self._ui_state: dict[str, Any] = {}
        self._entity_index_by_id: dict[str, int] = {}
        self._last_display_values: np.ndarray | None = None
        self._last_voltage_values: np.ndarray | None = None
        self._trace_segment_ids: list[str] = []
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
        return JaxleyAppSpecBuilder.DISPLAY_FIELD_ID

    def history_field_id(self) -> str:
        return JaxleyAppSpecBuilder.HISTORY_FIELD_ID

    def display_unit(self) -> str | None:
        return "mV"

    def history_unit(self) -> str | None:
        return self.display_unit()

    def morphology_color_map(self) -> str:
        return "scalar"

    def morphology_color_limits(self) -> tuple[float, float] | None:
        return (-80.0, 50.0)

    def morphology_color_norm(self) -> str:
        return "auto"

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

    def build_app_spec(self, *, geometry, display_values: np.ndarray, time_value: float) -> AppSpec:
        """Build the initial AppSpec from sampled values and morphology geometry."""

        controls = self.control_specs()
        actions = self._resolved_action_specs()
        trace_segment_ids, trace_times, trace_values = self._trace_field_snapshot()
        app_spec = JaxleyAppSpecBuilder.build_app_spec(
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

    def _initialize_model(self) -> np.ndarray:
        """Build Jaxley model, compile step function, return initial display_values."""

        print(f"[{self.title}] Importing JAX and Jaxley...")
        from jax import config as _jax_config
        _jax_config.update("jax_enable_x64", True)
        import jax  # noqa: F401
        import jaxley as jx
        from jaxley.integrate import build_init_and_step_fn

        print(f"[{self.title}] Building cells...")
        built = self.build_cells()
        self.cells = [built] if isinstance(built, jx.Cell) else list(built)

        print(f"[{self.title}] Building network ({len(self.cells)} cell(s))...")
        self.network = self.build_network(self.cells)

        print(f"[{self.title}] Setting up model...")
        self._runtime_handles = self.setup_model(self.network, self.cells)

        print(f"[{self.title}] Initializing gating variables at v_init={self.v_init} mV...")
        self.network.set("v", self.v_init)
        self.network.init_states()

        print(f"[{self.title}] Converting to JAX format...")
        self.network.delete_recordings()
        self.network.record("v", verbose=False)
        self.network.to_jax()
        params = self.network.get_parameters()

        print(f"[{self.title}] Tracing step function...")
        self._init_fn, self._step_fn = build_init_and_step_fn(self.network)

        print(f"[{self.title}] Compiling (first run may take a moment)...")
        self._state, self._all_params = self._init_fn(params, delta_t=self.dt)

        self._externals = {key: np.asarray(value) for key, value in self.network.externals.copy().items()}
        self._external_inds = {key: np.asarray(value) for key, value in self.network.external_inds.copy().items()}
        self._rec_indices = np.asarray(self.network.recordings.rec_index.to_numpy(), dtype=np.int32)
        self._rec_states = tuple(str(value) for value in self.network.recordings.state.to_numpy().tolist())
        self._time = 0.0
        self._step_index = 0

        print(f"[{self.title}] Building morphology geometry...")
        self.geometry = JaxleyAppSpecBuilder.build_morphology_geometry(
            self.network.nodes,
            xyzr=self.network.xyzr,
            cell_names=self.cell_names(self.cells),
        )
        display_values = self._read_display_values()
        self._entity_index_by_id = {entity_id: index for index, entity_id in enumerate(self.geometry.entity_ids)}
        self._initialize_trace_history(self._time, display_values)
        print(f"[{self.title}] Ready.")
        return display_values

    def build_startup_data(self) -> AppSpec:
        """Build Jaxley model and return a data-only AppSpec (no views or panels)."""

        display_values = self._initialize_model()
        trace_segment_ids, trace_times, trace_values = self._trace_field_snapshot()
        return JaxleyAppSpecBuilder.build_data_app_spec(
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
        """Build the Jaxley model, sample it once, and return the initial AppSpec."""

        display_values = self._initialize_model()
        return self.build_app_spec(
            geometry=self.geometry,
            display_values=display_values,
            time_value=self._time,
        )

    def initialize(self, app_spec: AppSpec) -> None:
        self._field_max_samples[self.history_field_id()] = self._resolved_field_max_samples(
            app_spec,
            field_id=self.history_field_id(),
            append_dim="time",
        )
        self._ui_state = {}

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
        """Update the simulation and emit incremental frontend updates."""

        t_target = self._time + self.sim_ms_per_frame()
        steps: list[Any] = []
        times: list[float] = []
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
            if self._time >= t_target:
                break

        times_array = np.asarray(times, dtype=np.float32)
        self._emit_batch(times_array, steps)

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
            display_values = self._read_display_values()
            self._initialize_trace_history(self._time, display_values)
            self.emit_update(self._display_field_replace(display_values))
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
