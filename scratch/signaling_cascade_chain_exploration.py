"""
Scratch exploration of chained SetpointRelaxEffector point processes.

This copies the bundled signaling cascade setup, then adds a second
SetpointRelaxEffector driven by the first effector's output:

    receptor.activation -> effector1.drive -> effector2.drive

Plots are split into three panels:
  - ligand/receptor state
  - effector 1 state
  - effector 2 state

Requires compiled bundled mechanisms under examples/neuron/signaling_cascade_mod/.
Compile from inside that directory (for example `nrnivmodl.bat .` on Windows or
`nrnivmodl .` on Unix/macOS).

Run: python scratch/signaling_cascade_chain_exploration.py
"""

from __future__ import annotations

from collections import deque
import math
from pathlib import Path
import time

import numpy as np
from neuron import h, load_mechanisms

from compneurovis import (
    AppSpec,
    AttributeRef,
    ControlPresentationSpec,
    ControlSpec,
    Field,
    LayoutSpec,
    LinePlotViewSpec,
    PanelSpec,
    ScalarValueSpec,
    Scene,
    SeriesSpec,
    run_app,
)
from compneurovis.session import BufferedSession, FieldAppend, FieldReplace, Reset, SetControl


h.load_file("stdrun.hoc")


TITLE = "Chained signaling cascade exploration"
DEFAULT_DT = 0.01
DEFAULT_DISPLAY_DT = 1.0
ROLLING_WINDOW_MS = 20.0
TIME_DIM = "time"
SERIES_DIM = "series"

CASCADE_FIELD_ID = "cascade"
EFFECTOR1_FIELD_ID = "effector1"
EFFECTOR2_FIELD_ID = "effector2"

CASCADE_VIEW_ID = "cascade_plot"
EFFECTOR1_VIEW_ID = "effector1_plot"
EFFECTOR2_VIEW_ID = "effector2_plot"

MECHANISM_DIR = Path(__file__).resolve().parents[1] / "examples" / "neuron" / "signaling_cascade_mod"


CASCADE_SERIES = (
    SeriesSpec("ligand_C", "Ligand C (uM)", source=AttributeRef("ligand", "C"), color=(100, 200, 255)),
    SeriesSpec("receptor_bound1", "Receptor bound1", source=AttributeRef("receptor", "bound1"), color=(255, 100, 100)),
    SeriesSpec("receptor_occupancy", "Receptor occupancy", source=AttributeRef("receptor", "occupancy"), color=(100, 255, 100)),
    SeriesSpec("receptor_activation", "Receptor activation", source=AttributeRef("receptor", "activation"), color=(180, 80, 255)),
)

EFFECTOR1_SERIES = (
    SeriesSpec("effector1_drive", "Drive", source=AttributeRef("receptor", "activation"), color=(150, 70, 210)),
    SeriesSpec("effector1_s", "s", source=AttributeRef("effector1", "s"), color=(255, 165, 0)),
    SeriesSpec("effector1_s_inf", "s_inf", source=AttributeRef("effector1", "s_inf"), color=(40, 40, 40)),
)

EFFECTOR2_SERIES = (
    SeriesSpec("effector2_drive", "Drive", source=AttributeRef("effector1", "effect"), color=(150, 70, 210)),
    SeriesSpec("effector2_s", "s", source=AttributeRef("effector2", "s"), color=(255, 165, 0)),
    SeriesSpec("effector2_s_inf", "s_inf", source=AttributeRef("effector2", "s_inf"), color=(40, 40, 40)),
)


def float_control(
    control_id: str,
    label: str,
    default: float,
    min_value: float,
    max_value: float,
    steps: int,
    target: AttributeRef,
    *,
    scale: str = "linear",
) -> ControlSpec:
    return ControlSpec(
        id=control_id,
        label=label,
        value_spec=ScalarValueSpec(default=default, min=min_value, max=max_value, value_type="float"),
        presentation=ControlPresentationSpec(kind="slider", steps=steps, scale=scale),
        send_to_session=True,
        target=target,
    )


def int_control(
    control_id: str,
    label: str,
    default: int,
    min_value: int,
    max_value: int,
    target: AttributeRef,
) -> ControlSpec:
    return ControlSpec(
        id=control_id,
        label=label,
        value_spec=ScalarValueSpec(default=default, min=min_value, max=max_value, value_type="int"),
        send_to_session=True,
        target=target,
    )


BASE_CONTROLS = (
    float_control(
        "external_input",
        "Ligand external_input (uM/ms)",
        0.005,
        0.0,
        0.1,
        200,
        AttributeRef("ligand", "external_input"),
    ),
    float_control(
        "decay_rate",
        "Ligand decay_rate (/ms)",
        0.00955,
        1e-05,
        0.1,
        200,
        AttributeRef("ligand", "decay_rate"),
        scale="log",
    ),
    float_control(
        "kd1",
        "Receptor Kd (uM)",
        3.09,
        0.01,
        10.0,
        200,
        AttributeRef("receptor", "kd1"),
        scale="log",
    ),
    float_control(
        "efficacy1",
        "Receptor efficacy1",
        1.0,
        0.0,
        2.0,
        200,
        AttributeRef("receptor", "efficacy1"),
    ),
    float_control(
        "decay1",
        "Receptor decay1 (/ms)",
        0.275,
        0.0001,
        1.0,
        200,
        AttributeRef("receptor", "decay1"),
        scale="log",
    ),
    float_control(
        "capacity",
        "Receptor capacity",
        1.62,
        0.0,
        5.0,
        200,
        AttributeRef("receptor", "capacity"),
    ),
    float_control(
        "baseline_activity",
        "Receptor baseline_activity",
        0.0,
        0.0,
        1.0,
        200,
        AttributeRef("receptor", "baseline_activity"),
    ),
)


def effector_controls(
    *,
    prefix: str,
    label_prefix: str,
    owner: str,
    default_k: float = 0.5,
    default_n: int = 3,
    default_tau_on: float = 151.0,
    default_tau_off: float = 140.0,
) -> tuple[ControlSpec, ...]:
    return (
        float_control(
            f"{prefix}_s_min",
            f"{label_prefix} s_min",
            0.0,
            0.0,
            1.0,
            100,
            AttributeRef(owner, "s_min"),
        ),
        float_control(
            f"{prefix}_s_max",
            f"{label_prefix} s_max",
            1.0,
            0.0,
            2.0,
            100,
            AttributeRef(owner, "s_max"),
        ),
        float_control(
            f"{prefix}_K",
            f"{label_prefix} K (Hill midpoint)",
            default_k,
            0.001,
            10.0,
            200,
            AttributeRef(owner, "K"),
            scale="log",
        ),
        int_control(
            f"{prefix}_n",
            f"{label_prefix} Hill coefficient n",
            default_n,
            1,
            6,
            AttributeRef(owner, "n"),
        ),
        float_control(
            f"{prefix}_tau_on",
            f"{label_prefix} tau_on (ms)",
            default_tau_on,
            1.0,
            400.0,
            200,
            AttributeRef(owner, "tau_on"),
        ),
        float_control(
            f"{prefix}_tau_off",
            f"{label_prefix} tau_off (ms)",
            default_tau_off,
            1.0,
            400.0,
            200,
            AttributeRef(owner, "tau_off"),
        ),
    )


CONTROLS = BASE_CONTROLS + effector_controls(prefix="effector1", label_prefix="Effector 1", owner="effector1") + effector_controls(
    prefix="effector2",
    label_prefix="Effector 2",
    owner="effector2",
    default_k=0.35,
    default_n=2,
    default_tau_on=220.0,
    default_tau_off=240.0,
)

CONTROL_BY_ID = {control.id: control for control in CONTROLS}


def control_specs(*, display_dt: float = DEFAULT_DISPLAY_DT, dt: float = DEFAULT_DT) -> dict[str, ControlSpec]:
    controls: dict[str, ControlSpec] = {
        "display_dt": ControlSpec(
            id="display_dt",
            label="Simulation speed (ms sim/update)",
            value_spec=ScalarValueSpec(default=max(float(dt), float(display_dt)), min=float(dt), max=20.0, value_type="float"),
            presentation=ControlPresentationSpec(kind="slider", steps=199, scale="log"),
            send_to_session=True,
        )
    }
    controls.update({control.id: control for control in CONTROLS})
    return controls


def ensure_bundled_mechanisms_loaded() -> None:
    if load_mechanisms(str(MECHANISM_DIR), warn_if_already_loaded=False):
        return
    raise RuntimeError(
        "Bundled NEURON mechanisms are not compiled. "
        f"From inside '{MECHANISM_DIR}', compile .mod files so NEURON can load "
        "nrnmech.dll on Windows or platform-specific libnrnmech.* on Unix/macOS."
    )


def zero_series_history(series: tuple[SeriesSpec, ...]) -> dict[str, list[float]]:
    return {entry.key: [0.0] for entry in series}


def build_field(
    *,
    field_id: str,
    series: tuple[SeriesSpec, ...],
    time_history: list[float],
    series_history: dict[str, list[float]],
    unit: str,
) -> Field:
    return Field(
        id=field_id,
        values=np.asarray([series_history[entry.key] for entry in series], dtype=np.float32),
        dims=(SERIES_DIM, TIME_DIM),
        coords={
            SERIES_DIM: np.asarray([entry.label for entry in series]),
            TIME_DIM: np.asarray(time_history, dtype=np.float32),
        },
        unit=unit,
    )


def build_view(
    *,
    view_id: str,
    title: str,
    field_id: str,
    series: tuple[SeriesSpec, ...],
    y_max: float,
) -> LinePlotViewSpec:
    return LinePlotViewSpec(
        id=view_id,
        title=title,
        field_id=field_id,
        x_dim=TIME_DIM,
        series_dim=SERIES_DIM,
        x_label="Time",
        x_unit="ms",
        y_label="Signal",
        colors={entry.label: entry.color for entry in series},
        show_legend=True,
        rolling_window=ROLLING_WINDOW_MS,
        trim_to_rolling_window=True,
        y_min=0.0,
        y_max=y_max,
        x_major_tick_spacing=5.0,
        x_minor_tick_spacing=1.0,
        max_refresh_hz=120.0,
    )


def build_scene(
    *,
    time_history: list[float],
    cascade_history: dict[str, list[float]],
    effector1_history: dict[str, list[float]],
    effector2_history: dict[str, list[float]],
    controls: dict[str, ControlSpec],
) -> Scene:
    cascade_field = build_field(
        field_id=CASCADE_FIELD_ID,
        series=CASCADE_SERIES,
        time_history=time_history,
        series_history=cascade_history,
        unit="a.u.",
    )
    effector1_field = build_field(
        field_id=EFFECTOR1_FIELD_ID,
        series=EFFECTOR1_SERIES,
        time_history=time_history,
        series_history=effector1_history,
        unit="a.u.",
    )
    effector2_field = build_field(
        field_id=EFFECTOR2_FIELD_ID,
        series=EFFECTOR2_SERIES,
        time_history=time_history,
        series_history=effector2_history,
        unit="a.u.",
    )

    views = {
        CASCADE_VIEW_ID: build_view(
            view_id=CASCADE_VIEW_ID,
            title="Ligand and receptor",
            field_id=CASCADE_FIELD_ID,
            series=CASCADE_SERIES,
            y_max=2.2,
        ),
        EFFECTOR1_VIEW_ID: build_view(
            view_id=EFFECTOR1_VIEW_ID,
            title="Setpoint relax effector 1",
            field_id=EFFECTOR1_FIELD_ID,
            series=EFFECTOR1_SERIES,
            y_max=1.2,
        ),
        EFFECTOR2_VIEW_ID: build_view(
            view_id=EFFECTOR2_VIEW_ID,
            title="Setpoint relax effector 2",
            field_id=EFFECTOR2_FIELD_ID,
            series=EFFECTOR2_SERIES,
            y_max=1.2,
        ),
    }

    return Scene(
        fields={
            cascade_field.id: cascade_field,
            effector1_field.id: effector1_field,
            effector2_field.id: effector2_field,
        },
        geometries={},
        views=views,
        controls=controls,
        layout=LayoutSpec(
            title=TITLE,
            panels=(
                PanelSpec(id="cascade-panel", kind="line_plot", view_ids=(CASCADE_VIEW_ID,)),
                PanelSpec(id="effector1-panel", kind="line_plot", view_ids=(EFFECTOR1_VIEW_ID,)),
                PanelSpec(id="effector2-panel", kind="line_plot", view_ids=(EFFECTOR2_VIEW_ID,)),
                PanelSpec(id="controls-panel", kind="controls", control_ids=tuple(controls.keys())),
            ),
            panel_grid=(("cascade-panel", "effector1-panel"), ("effector2-panel", "controls-panel")),
        ),
    )


class ChainedSignalingCascadeSession(BufferedSession):
    @classmethod
    def startup_scene(cls) -> Scene | None:
        return build_scene(
            time_history=[0.0],
            cascade_history=zero_series_history(CASCADE_SERIES),
            effector1_history=zero_series_history(EFFECTOR1_SERIES),
            effector2_history=zero_series_history(EFFECTOR2_SERIES),
            controls=control_specs(),
        )

    def __init__(
        self,
        *,
        dt: float = DEFAULT_DT,
        display_dt: float = DEFAULT_DISPLAY_DT,
        v_init: float = -65.0,
        max_samples: int = 5000,
    ) -> None:
        super().__init__()
        self.dt = float(dt)
        if self.dt <= 0:
            raise ValueError("ChainedSignalingCascadeSession dt must be positive")
        self.display_dt = max(self.dt, float(display_dt))
        if self.display_dt <= 0:
            raise ValueError("ChainedSignalingCascadeSession display_dt must be positive")
        self.v_init = float(v_init)
        self.max_samples = int(max_samples)
        if self.max_samples <= 0:
            raise ValueError("ChainedSignalingCascadeSession max_samples must be positive")

        self.parameters = {control.id: control.default_value() for control in CONTROLS}

        self._time_history: deque[float] = deque(maxlen=self.max_samples)
        self._cascade_history: dict[str, deque[float]] = {}
        self._effector1_history: dict[str, deque[float]] = {}
        self._effector2_history: dict[str, deque[float]] = {}

        self.soma = None
        self.ligand = None
        self.receptor = None
        self.effector1 = None
        self.effector2 = None

    def control_specs(self) -> dict[str, ControlSpec]:
        return control_specs(display_dt=self.display_dt, dt=self.dt)

    def initialize(self) -> Scene:
        ensure_bundled_mechanisms_loaded()
        self._build_model()
        h.dt = self.dt
        h.finitialize(self.v_init)
        self._reset_history()
        self._capture_sample()
        return build_scene(
            time_history=list(self._time_history),
            cascade_history={key: list(values) for key, values in self._cascade_history.items()},
            effector1_history={key: list(values) for key, values in self._effector1_history.items()},
            effector2_history={key: list(values) for key, values in self._effector2_history.items()},
            controls=self.control_specs(),
        )

    def idle_sleep(self) -> float:
        return 1.0 / 60.0

    def advance(self) -> None:
        step_count = self._steps_per_update()
        time_values = np.empty(step_count, dtype=np.float32)
        cascade_values = np.empty((len(CASCADE_SERIES), step_count), dtype=np.float32)
        effector1_values = np.empty((len(EFFECTOR1_SERIES), step_count), dtype=np.float32)
        effector2_values = np.empty((len(EFFECTOR2_SERIES), step_count), dtype=np.float32)

        for step_index in range(step_count):
            h.fadvance()
            sample_time, cascade_sample, effector1_sample, effector2_sample = self._capture_sample()
            time_values[step_index] = sample_time
            cascade_values[:, step_index] = cascade_sample
            effector1_values[:, step_index] = effector1_sample
            effector2_values[:, step_index] = effector2_sample

        for update in self._field_appends(
            time_values=time_values,
            cascade_values=cascade_values,
            effector1_values=effector1_values,
            effector2_values=effector2_values,
        ):
            self.emit(update)

    def handle(self, command) -> None:
        if isinstance(command, Reset):
            h.finitialize(self.v_init)
            self._reset_history()
            self._capture_sample()
            for update in self._field_replaces():
                self.emit(update)
            return
        if isinstance(command, SetControl):
            self.apply_control(command.control_id, command.value)

    def shutdown(self) -> None:
        self.soma = None
        self.ligand = None
        self.receptor = None
        self.effector1 = None
        self.effector2 = None

    def _build_model(self) -> None:
        t0 = time.perf_counter()

        soma = h.Section(name="soma")
        soma.L = 20.0
        soma.diam = 20.0
        soma.nseg = 1
        soma.Ra = 150.0
        soma.cm = 1.0
        soma.insert("pas")
        for seg in soma:
            seg.pas.g = 1e-4
            seg.pas.e = -65.0

        self.soma = soma
        self.ligand = h.GenericLigand(soma(0.5))
        self.ligand.C_init = 0.0

        self.receptor = h.GenericReceptor(soma(0.5))
        self.receptor.n_ligands = 1
        h.setpointer(self.ligand._ref_C, "C_lig1", self.receptor)
        h.setpointer(self.ligand._ref_C_init, "C_lig2", self.receptor)
        h.setpointer(self.ligand._ref_C_init, "C_lig3", self.receptor)
        h.setpointer(self.ligand._ref_C_init, "C_lig4", self.receptor)

        self.effector1 = h.SetpointRelaxEffector(soma(0.5))
        self.effector2 = h.SetpointRelaxEffector(soma(0.5))
        h.setpointer(self.receptor._ref_activation, "drive", self.effector1)
        h.setpointer(self.effector1._ref_effect, "drive", self.effector2)

        for control in CONTROLS:
            self._apply_parameter_to_model(control.id)

        print(f"Chained signaling cascade built in {time.perf_counter() - t0:.2f}s")

    def _apply_parameter_to_model(self, control_id: str) -> None:
        control = CONTROL_BY_ID[control_id]
        value = self.parameters[control_id]
        if isinstance(control.value_spec, ScalarValueSpec) and control.value_spec.value_type == "int":
            value = int(round(float(value)))
        else:
            value = float(value)
        if control.target is not None:
            control.target.write(self, value)

    def _reset_history(self) -> None:
        self._time_history = deque(maxlen=self.max_samples)
        self._cascade_history = {entry.key: deque(maxlen=self.max_samples) for entry in CASCADE_SERIES}
        self._effector1_history = {entry.key: deque(maxlen=self.max_samples) for entry in EFFECTOR1_SERIES}
        self._effector2_history = {entry.key: deque(maxlen=self.max_samples) for entry in EFFECTOR2_SERIES}

    def _steps_per_update(self) -> int:
        return max(1, int(math.ceil(self.display_dt / self.dt)))

    def _read_series_values(self, series: tuple[SeriesSpec, ...]) -> np.ndarray:
        return np.asarray([float(entry.source.read(self)) for entry in series], dtype=np.float32)

    def _capture_sample(self) -> tuple[float, np.ndarray, np.ndarray, np.ndarray]:
        time_value = float(h.t)
        cascade_sample = self._read_series_values(CASCADE_SERIES)
        effector1_sample = self._read_series_values(EFFECTOR1_SERIES)
        effector2_sample = self._read_series_values(EFFECTOR2_SERIES)

        self._time_history.append(time_value)
        for index, entry in enumerate(CASCADE_SERIES):
            self._cascade_history[entry.key].append(float(cascade_sample[index]))
        for index, entry in enumerate(EFFECTOR1_SERIES):
            self._effector1_history[entry.key].append(float(effector1_sample[index]))
        for index, entry in enumerate(EFFECTOR2_SERIES):
            self._effector2_history[entry.key].append(float(effector2_sample[index]))

        return time_value, cascade_sample, effector1_sample, effector2_sample

    def _field_replaces(self) -> tuple[FieldReplace, ...]:
        return (
            FieldReplace(
                field_id=CASCADE_FIELD_ID,
                values=np.asarray([list(self._cascade_history[entry.key]) for entry in CASCADE_SERIES], dtype=np.float32),
                coords={
                    SERIES_DIM: np.asarray([entry.label for entry in CASCADE_SERIES]),
                    TIME_DIM: np.asarray(list(self._time_history), dtype=np.float32),
                },
            ),
            FieldReplace(
                field_id=EFFECTOR1_FIELD_ID,
                values=np.asarray([list(self._effector1_history[entry.key]) for entry in EFFECTOR1_SERIES], dtype=np.float32),
                coords={
                    SERIES_DIM: np.asarray([entry.label for entry in EFFECTOR1_SERIES]),
                    TIME_DIM: np.asarray(list(self._time_history), dtype=np.float32),
                },
            ),
            FieldReplace(
                field_id=EFFECTOR2_FIELD_ID,
                values=np.asarray([list(self._effector2_history[entry.key]) for entry in EFFECTOR2_SERIES], dtype=np.float32),
                coords={
                    SERIES_DIM: np.asarray([entry.label for entry in EFFECTOR2_SERIES]),
                    TIME_DIM: np.asarray(list(self._time_history), dtype=np.float32),
                },
            ),
        )

    def _field_appends(
        self,
        *,
        time_values: np.ndarray,
        cascade_values: np.ndarray,
        effector1_values: np.ndarray,
        effector2_values: np.ndarray,
    ) -> tuple[FieldAppend, ...]:
        return (
            FieldAppend(
                field_id=CASCADE_FIELD_ID,
                append_dim=TIME_DIM,
                values=cascade_values,
                coord_values=time_values,
                max_length=self.max_samples,
            ),
            FieldAppend(
                field_id=EFFECTOR1_FIELD_ID,
                append_dim=TIME_DIM,
                values=effector1_values,
                coord_values=time_values,
                max_length=self.max_samples,
            ),
            FieldAppend(
                field_id=EFFECTOR2_FIELD_ID,
                append_dim=TIME_DIM,
                values=effector2_values,
                coord_values=time_values,
                max_length=self.max_samples,
            ),
        )

    def apply_control(self, control_id: str, value) -> bool:
        if control_id == "display_dt":
            try:
                self.display_dt = max(self.dt, float(value))
                return True
            except Exception:
                return False

        control = CONTROL_BY_ID.get(control_id)
        if control is None:
            return False

        try:
            if isinstance(control.value_spec, ScalarValueSpec) and control.value_spec.value_type == "int":
                coerced = int(round(float(value)))
            else:
                coerced = float(value)
            self.parameters[control_id] = coerced
            if control.target is not None and getattr(self, control.target.owner, None) is not None:
                self._apply_parameter_to_model(control_id)
            return True
        except Exception:
            return False


run_app(
    AppSpec(
        session=ChainedSignalingCascadeSession,
        title=TITLE,
    )
)
