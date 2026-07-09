"""scratch/complex_cell_neuron_attach_demo.py - complex SWC cell HH demo.

Reimplemented on the current source API (the old ``cnv.neuron.attach`` path is
gone). Demo surface:
  - morphology colored by a selectable HH/voltage variable (dropdown)
  - selected-segment voltage history (title bound to the selected compartment)
  - selected-segment HH gate history
  - controls for dt, stimulation, HH conductances, passive properties, temperature

Requires: NEURON, res/Animal_2_Basal_2.CNG.swc
Run: python scratch/complex_cell_neuron_attach_demo.py
"""

from __future__ import annotations

from pathlib import Path

from neuron import h

import compneurovis as cnv
from compneurovis.backends.neuron.utils import load_swc_neuron


DT = 0.1
DISPLAY_DT = 0.1
V_INIT = -65.0
DEMO_NSEG = 10
PULSE_COUNT = 5
FIRST_PULSE_DELAY = 2.0

HH_DISPLAY_VARIABLES = {
    "Voltage": "v",
    "m gate": "m_hh",
    "h gate": "h_hh",
    "n gate": "n_hh",
}

HH_GATE_VARIABLES = {
    "m": "m_hh",
    "h": "h_hh",
    "n": "n_hh",
}

VOLTAGE_TRACE_COLOR = "#CC3311"
HH_GATE_TRACE_COLORS = {
    "m": "#00CC66",
    "h": "#4169E1",
    "n": "#E69F00",
}
MORPHOLOGY_COLOR_LIMITS = {
    "Voltage": (-80.0, 50.0),
    "m gate": (0.0, 1.0),
    "h gate": (0.0, 1.0),
    "n gate": (0.0, 1.0),
}
# Morphology colormap per variable: a two-color ramp ending at that variable's
# trace color (so picking it in the dropdown recolors the cell to match its line).
# Low ends are complementary/contrasting colors -- never white -- so the cell
# stays visible against the white background across the whole value range.
# ``ramp:`` colors are colon-separated (ramp:<low>:<high>).
MORPHOLOGY_COLOR_MAPS = {
    "Voltage": f"ramp:#3366CC:{VOLTAGE_TRACE_COLOR}",      # blue -> red
    "m gate": f"ramp:#CC0066:{HH_GATE_TRACE_COLORS['m']}",  # magenta -> green
    "h gate": f"ramp:#E19941:{HH_GATE_TRACE_COLORS['h']}",  # orange -> royal blue
    "n gate": f"ramp:#0047E6:{HH_GATE_TRACE_COLORS['n']}",  # blue -> orange
}
SOMA_ENTITY_ID = "soma[0]@0.50000"

params = {
    "dt": DT,
    "stim_amp": 1.0,
    "pulse_width": 5.0,
    "pulse_spacing": 20.0,
    "pulse_offset": 0.0,
    "gnabar_hh": 0.12,
    "gkbar_hh": 0.036,
    "gl_hh": 0.0003,
    "el_hh": -54.3,
    "cm": 1.0,
    "ra": 35.4,
    "celsius": 6.3,
}


def load_sections() -> list:
    repo_root = Path(__file__).resolve().parents[1]
    swc_path = repo_root / "res" / "Animal_2_Basal_2.CNG.swc"
    if not swc_path.is_file():
        raise FileNotFoundError(f"SWC file not found: {swc_path}")
    return load_swc_neuron(str(swc_path))


def configure_cell(sections: list) -> list:
    for sec in sections:
        sec.insert("hh")
        if "soma" not in sec.name().lower():
            sec.nseg = DEMO_NSEG
        sec.cm = params["cm"]
        sec.Ra = params["ra"]
        for seg in sec:
            seg.gnabar_hh = params["gnabar_hh"]
            seg.gkbar_hh = params["gkbar_hh"]
            seg.gl_hh = params["gl_hh"]
            seg.el_hh = params["el_hh"]

    somas = [sec for sec in sections if "soma" in sec.name().lower()]
    if not somas:
        raise RuntimeError("No soma sections found for stimulation")
    clamps = [h.IClamp(soma(0.5)) for soma in somas for _ in range(PULSE_COUNT)]
    update_clamps(clamps)
    return clamps


def update_clamps(clamps: list) -> None:
    for index, clamp in enumerate(clamps):
        clamp.delay = params["pulse_offset"] + FIRST_PULSE_DELAY + index * params["pulse_spacing"]
        clamp.dur = params["pulse_width"]
        clamp.amp = params["stim_amp"]


def set_clamp_param(name: str, value: float) -> None:
    params[name] = float(value)
    update_clamps(clamps)


def set_segment_param(name: str, value: float) -> None:
    params[name] = float(value)
    for sec in sections:
        for seg in sec:
            setattr(seg, name, float(value))


def set_section_param(name: str, value: float) -> None:
    params[name] = float(value)
    attr = "Ra" if name == "ra" else name
    for sec in sections:
        setattr(sec, attr, float(value))


def set_celsius(value: float) -> None:
    params["celsius"] = float(value)
    h.celsius = float(value)


def set_sim_dt(ctx, value: float) -> None:
    params["dt"] = float(value)
    ctx.backend.dt = params["dt"]
    h.dt = params["dt"]


h.dt = DT
h.celsius = params["celsius"]

sections = load_sections()
clamps = configure_cell(sections)
h.finitialize(V_INIT)

src = cnv.neuron.source(
    sections=sections,
    dt=DT,
    display_dt=DISPLAY_DT,
    v_init=V_INIT,
    title="Complex cell HH demo",
)

display = src.segment_variable_display(
    "morphology_variable",
    variables=HH_DISPLAY_VARIABLES,
    default="Voltage",
    label="Morphology color",
    units={"Voltage": "mV"},
    color_limits=MORPHOLOGY_COLOR_LIMITS,
    color_maps=MORPHOLOGY_COLOR_MAPS,
)
morph = src.morphology(
    variable="v",
    name="Morphology",
    unit="mV",
    color_field_id=display.field_id,
    color_limits=None,
    selected=SOMA_ENTITY_ID,
)
volt = src.segment_variable_history(
    "Selected voltage",
    variables={"Voltage": "v"},
    panel_title="Selected segment voltage",
    y_label="Membrane potential",
    y_unit="mV",
    rolling_window=250.0,
    series_colors={"Voltage": VOLTAGE_TRACE_COLOR},
)
gates = src.segment_variable_history(
    "hh_gates",
    variables=HH_GATE_VARIABLES,
    panel_title="HH gating variables",
    y_label="Open probability",
    rolling_window=250.0,
    max_samples=12000,
    y_min=-0.05,
    y_max=1.05,
    series_colors=HH_GATE_TRACE_COLORS,
)

src.control(
    "dt",
    label="Simulation dt (ms)",
    get=lambda: params["dt"],
    set=set_sim_dt,
    min=0.025,
    max=0.5,
)
src.control(
    "stim_amp",
    label="Stimulus amplitude (nA)",
    get=lambda: params["stim_amp"],
    set=lambda ctx, value: set_clamp_param("stim_amp", value),
    min=0.0,
    max=2.0,
)
src.control(
    "pulse_width",
    label="Pulse width (ms)",
    get=lambda: params["pulse_width"],
    set=lambda ctx, value: set_clamp_param("pulse_width", value),
    min=1.0,
    max=20.0,
)
src.control(
    "pulse_spacing",
    label="Pulse spacing (ms)",
    get=lambda: params["pulse_spacing"],
    set=lambda ctx, value: set_clamp_param("pulse_spacing", value),
    min=5.0,
    max=40.0,
)
src.control(
    "gnabar_hh",
    label="Na conductance (S/cm^2)",
    get=lambda: params["gnabar_hh"],
    set=lambda ctx, value: set_segment_param("gnabar_hh", value),
    min=0.02,
    max=0.24,
)
src.control(
    "gkbar_hh",
    label="K conductance (S/cm^2)",
    get=lambda: params["gkbar_hh"],
    set=lambda ctx, value: set_segment_param("gkbar_hh", value),
    min=0.005,
    max=0.12,
)
src.control(
    "gl_hh",
    label="Leak conductance (S/cm^2)",
    get=lambda: params["gl_hh"],
    set=lambda ctx, value: set_segment_param("gl_hh", value),
    min=0.00005,
    max=0.001,
)
src.control(
    "el_hh",
    label="Leak reversal (mV)",
    get=lambda: params["el_hh"],
    set=lambda ctx, value: set_segment_param("el_hh", value),
    min=-80.0,
    max=-40.0,
)
src.control(
    "cm",
    label="Membrane capacitance (uF/cm^2)",
    get=lambda: params["cm"],
    set=lambda ctx, value: set_section_param("cm", value),
    min=0.2,
    max=3.0,
)
src.control(
    "ra",
    label="Axial resistance (ohm cm)",
    get=lambda: params["ra"],
    set=lambda ctx, value: set_section_param("ra", value),
    min=20.0,
    max=200.0,
)
src.control(
    "celsius",
    label="Temperature (C)",
    get=lambda: params["celsius"],
    set=lambda ctx, value: set_celsius(value),
    min=2.0,
    max=37.0,
)
src.action("reset", label="Reset", fn=lambda ctx: h.finitialize(V_INIT), resets_fields=True)

cnv.layout(((morph, volt), (gates, src.controls_panel)))

cnv.show(title="Complex cell HH demo")
