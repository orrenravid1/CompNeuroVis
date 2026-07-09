"""Leaky integrate-and-fire model using source-level inline authoring.

Run: python examples/custom/lif_backend.py
"""

from __future__ import annotations

import math

import compneurovis as cnv


DT_MS = 0.25


class LIFModel:
    def __init__(self) -> None:
        self.rest_voltage_mv = -68.0
        self.reset_voltage_mv = -72.0
        self.threshold_voltage_mv = -50.0
        self.membrane_tau_ms = 18.0
        self.membrane_resistance_mohm = 10.0
        self.tonic_current_na = 1.7
        self.pulse_amplitude_na = 2.8
        self.pulse_decay_ms = 14.0
        self.refractory_ms = 2.5
        self.t_ms = 0.0
        self.reset()

    def reset(self) -> None:
        self.t_ms = 0.0
        self.v_mv = self.rest_voltage_mv
        self.pulse_current_na = 0.0
        self.refractory_remaining_ms = 0.0
        self.spike_flag = 0.0

    def deliver_pulse(self) -> None:
        self.pulse_current_na = max(0.0, self.pulse_current_na + self.pulse_amplitude_na)

    @property
    def total_current_na(self) -> float:
        return self.tonic_current_na + self.pulse_current_na

    @property
    def refractory_fraction(self) -> float:
        if self.refractory_remaining_ms <= 0.0:
            return 0.0
        return min(1.0, self.refractory_remaining_ms / max(1e-6, self.refractory_ms))

    def step(self, dt_ms: float = DT_MS) -> None:
        self.t_ms += dt_ms
        self.spike_flag = 0.0
        decay = dt_ms / max(1e-6, self.pulse_decay_ms)
        self.pulse_current_na = max(0.0, self.pulse_current_na * math.exp(-decay))
        if self.refractory_remaining_ms > 0.0:
            self.refractory_remaining_ms = max(0.0, self.refractory_remaining_ms - dt_ms)
            self.v_mv = self.reset_voltage_mv
            return
        drive_mv = self.membrane_resistance_mohm * self.total_current_na
        dvdt = (self.rest_voltage_mv - self.v_mv + drive_mv) / max(1e-6, self.membrane_tau_ms)
        self.v_mv += dt_ms * dvdt
        if self.v_mv >= self.threshold_voltage_mv:
            self.spike_flag = 1.0
            self.v_mv = self.reset_voltage_mv
            self.refractory_remaining_ms = max(0.0, self.refractory_ms)


model = LIFModel()
src = cnv.source(lambda ctx: model.step())

voltage = src.line(
    "Voltage",
    x=lambda: model.t_ms,
    read={
        "Membrane": lambda: model.v_mv,
        "Threshold": lambda: model.threshold_voltage_mv,
        "Reset": lambda: model.reset_voltage_mv,
    },
    y_label="Voltage",
    y_unit="mV",
    rolling_window=500.0,
    y_min=-80.0,
    y_max=-40.0,
    series_colors={"Membrane": "#00d2be", "Threshold": "#d1495b", "Reset": "#6c757d"},
)
current = src.line(
    "Current",
    x=lambda: model.t_ms,
    read={
        "Tonic drive": lambda: model.tonic_current_na,
        "Pulse drive": lambda: model.pulse_current_na,
        "Total drive": lambda: model.total_current_na,
    },
    y_label="Current",
    y_unit="nA",
    rolling_window=500.0,
    y_min=0.0,
    y_max=6.0,
    series_colors={"Tonic drive": "#2356b8", "Pulse drive": "#ff8c00", "Total drive": "#7d3cff"},
)
events = src.line(
    "Events",
    x=lambda: model.t_ms,
    read={
        "Spike": lambda: model.spike_flag,
        "Refractory": lambda: model.refractory_fraction,
    },
    y_label="State",
    rolling_window=500.0,
    y_min=-0.05,
    y_max=1.05,
    series_colors={"Spike": "#ff3366", "Refractory": "#2f9e44"},
)


def set_membrane_tau_ms(value: float) -> None:
    model.membrane_tau_ms = float(value)


def set_membrane_resistance_mohm(value: float) -> None:
    model.membrane_resistance_mohm = float(value)


def set_tonic_current_na(value: float) -> None:
    model.tonic_current_na = float(value)


def set_pulse_amplitude_na(value: float) -> None:
    model.pulse_amplitude_na = float(value)


def set_pulse_decay_ms(value: float) -> None:
    model.pulse_decay_ms = float(value)


def set_threshold_voltage_mv(value: float) -> None:
    model.threshold_voltage_mv = float(value)


def set_refractory_ms(value: float) -> None:
    model.refractory_ms = float(value)


def slider(
    name: str,
    label: str,
    get_value,
    set_value,
    min_value: float,
    max_value: float,
    steps: int,
    *,
    scale: str = "linear",
):
    src.control(
        name,
        label=label,
        get=get_value,
        set=lambda ctx, value: set_value(value),
        min=min_value,
        max=max_value,
        presentation=cnv.ControlPresentationSpec(kind="slider", steps=steps, scale=scale),
    )


slider("membrane_tau_ms", "Membrane tau (ms)", lambda: model.membrane_tau_ms, set_membrane_tau_ms, 2.0, 80.0, 195, scale="log")
slider("membrane_resistance_mohm", "Resistance (MOhm)", lambda: model.membrane_resistance_mohm, set_membrane_resistance_mohm, 1.0, 25.0, 240)
slider("tonic_current_na", "Tonic drive (nA)", lambda: model.tonic_current_na, set_tonic_current_na, 0.0, 4.0, 200)
slider("pulse_amplitude_na", "Pulse amplitude (nA)", lambda: model.pulse_amplitude_na, set_pulse_amplitude_na, 0.0, 8.0, 240)
slider("pulse_decay_ms", "Pulse decay (ms)", lambda: model.pulse_decay_ms, set_pulse_decay_ms, 2.0, 80.0, 195, scale="log")
slider("threshold_voltage_mv", "Threshold (mV)", lambda: model.threshold_voltage_mv, set_threshold_voltage_mv, -65.0, -35.0, 150)
slider("refractory_ms", "Refractory (ms)", lambda: model.refractory_ms, set_refractory_ms, 0.5, 12.0, 115)
src.action("pulse", label="Pulse", fn=lambda ctx: model.deliver_pulse())
src.action("reset", label="Reset", fn=lambda ctx: model.reset(), resets_fields=True)

cnv.layout(((voltage,), (current, events), (src.controls_panel,)))

cnv.show(title="Custom LIF model")
