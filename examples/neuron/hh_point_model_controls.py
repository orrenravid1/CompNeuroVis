"""HH point-model controls using source-level inline authoring.

Requires: NEURON
Run: python examples/neuron/hh_point_model_controls.py
"""

from __future__ import annotations

from neuron import h

import compneurovis as cnv


DT = 0.025
POINT_LENGTH_UM = 12.6157
POINT_DIAM_UM = 12.6157
CONTINUOUS_CLAMP_DUR_MS = 1.0e9

params = {
    "display_dt": 0.1,
    "clamp_amp": 0.0,
    "gnabar": 0.12,
    "gkbar": 0.036,
    "gl": 0.0003,
    "el": -54.3,
    "ena": 50.0,
    "ek": -77.0,
    "cm": 1.0,
    "celsius": 6.3,
}

sec = h.Section(name="hh_point")
sec.L = POINT_LENGTH_UM
sec.diam = POINT_DIAM_UM
sec.nseg = 1
sec.insert("hh")
seg = sec(0.5)
clamp = h.IClamp(seg)
clamp.delay = 0.0
clamp.dur = CONTINUOUS_CLAMP_DUR_MS


def apply_runtime_parameters() -> None:
    h.celsius = float(params["celsius"])
    sec.cm = float(params["cm"])
    for item in sec:
        item.gnabar_hh = float(params["gnabar"])
        item.gkbar_hh = float(params["gkbar"])
        item.gl_hh = float(params["gl"])
        item.el_hh = float(params["el"])
        item.ena = float(params["ena"])
        item.ek = float(params["ek"])
    clamp.amp = float(params["clamp_amp"])


def set_param(name: str, value: float) -> None:
    params[name] = float(value)
    apply_runtime_parameters()


apply_runtime_parameters()
src = cnv.neuron.source(sections=[sec], dt=DT, display_dt=params["display_dt"])
voltage = src.line_refs(
    "Voltage",
    refs=(seg._ref_v,),
    series=("Voltage",),
    unit="mV",
    rolling_window=80.0,
    y_label="Voltage",
    y_unit="mV",
    y_min=-85.0,
    y_max=55.0,
    pen="#00d2be",
    max_refresh_hz=15.0,
)
current = src.line_refs(
    "Input current",
    refs=(clamp._ref_i,),
    series=("Input current",),
    unit="nA",
    rolling_window=80.0,
    y_label="Current",
    y_unit="nA",
    y_min=-0.25,
    y_max=0.55,
    pen="#2356b8",
    max_refresh_hz=15.0,
)
gating = src.line_refs(
    "Gating",
    refs=(seg._ref_m_hh, seg._ref_h_hh, seg._ref_n_hh),
    series=("m", "h", "n"),
    rolling_window=80.0,
    y_label="Gate value",
    y_min=-0.05,
    y_max=1.05,
    show_legend=True,
    series_colors={"m": "#ff8c00", "h": "#ff50b4", "n": "#7d3cff"},
    max_refresh_hz=15.0,
)


def slider(name: str, label: str, min_value: float, max_value: float, steps: int):
    src.control(
        name,
        label=label,
        get=lambda name=name: params[name],
        set=lambda ctx, value, name=name: set_param(name, value),
        min=min_value,
        max=max_value,
        presentation=cnv.ControlPresentationSpec(kind="slider", steps=steps),
    )


src.control(
    "display_dt",
    label="Visual update interval (ms sim/update)",
    get=lambda: params["display_dt"],
    set=lambda ctx, value: setattr(ctx.backend, "display_dt", max(DT, float(value))),
    min=DT,
    max=4.0,
    presentation=cnv.ControlPresentationSpec(kind="slider", steps=159),
)
slider("clamp_amp", "IClamp amplitude (nA)", -0.20, 0.50, 280)
slider("gnabar", "Na conductance gNa (S/cm^2)", 0.01, 0.30, 290)
slider("gkbar", "K conductance gK (S/cm^2)", 0.005, 0.10, 190)
slider("gl", "Leak conductance gL (S/cm^2)", 0.00005, 0.005, 220)
slider("el", "Leak reversal EL (mV)", -80.0, -30.0, 250)
slider("ena", "Na reversal ENa (mV)", 35.0, 80.0, 225)
slider("ek", "K reversal EK (mV)", -110.0, -50.0, 240)
slider("cm", "Membrane capacitance Cm (uF/cm^2)", 0.2, 3.0, 280)
slider("celsius", "Temperature (degC)", 3.0, 37.0, 340)
src.action("reset", label="Reset", fn=lambda ctx: h.finitialize(-65.0), resets_fields=True)

cnv.layout(((voltage, current), (gating, src.controls_panel)))

cnv.show(title="HH point-model controls")
