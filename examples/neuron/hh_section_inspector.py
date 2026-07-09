"""HH section inspector using source-level inline authoring.

Requires: NEURON
Run: python examples/neuron/hh_section_inspector.py
"""

from __future__ import annotations

from neuron import h

import compneurovis as cnv


def straight_section(name: str, start: tuple[float, float, float], end: tuple[float, float, float], diam: float, nseg: int):
    sec = h.Section(name=name)
    sec.nseg = int(nseg)
    sec.pt3dclear()
    sec.pt3dadd(float(start[0]), float(start[1]), float(start[2]), float(diam))
    sec.pt3dadd(float(end[0]), float(end[1]), float(end[2]), float(diam))
    sec.insert("hh")
    sec.Ra = 100.0
    sec.cm = 1.0
    return sec


soma = straight_section("soma", (-12.0, 0.0, 0.0), (12.0, 0.0, 0.0), 18.0, 1)
apical = straight_section("apical", (12.0, 0.0, 0.0), (112.0, 44.0, 8.0), 3.5, 9)
basal = straight_section("basal", (-12.0, 0.0, 0.0), (-108.0, -42.0, -8.0), 3.0, 7)
axon_initial = straight_section("axon_initial", (-12.0, 0.0, 0.0), (-12.0, 0.0, 56.0), 1.8, 7)
axon_distal = straight_section("axon_distal", (-12.0, 0.0, 56.0), (-12.0, 0.0, 186.0), 1.2, 9)
apical.connect(soma(1.0))
basal.connect(soma(0.0))
axon_initial.connect(soma(0.0))
axon_distal.connect(axon_initial(1.0))
sections = [soma, apical, basal, axon_initial, axon_distal]

stim_scale = {"value": 1.0}
clamp_specs = []
for section_name, pulses in {
    "soma": ((8.0, 4.0, 1.00), (42.0, 5.0, 0.85), (78.0, 4.0, 1.05)),
    "apical": ((24.0, 6.0, 0.35), (60.0, 6.0, 0.35)),
    "basal": ((50.0, 8.0, -0.18),),
}.items():
    sec = {item.name(): item for item in sections}[section_name]
    for delay, dur, base_amp in pulses:
        clamp = h.IClamp(sec(0.5))
        clamp.delay = delay
        clamp.dur = dur
        clamp.amp = stim_scale["value"] * base_amp
        clamp_specs.append((clamp, base_amp))


def set_stim_scale(ctx, value: float) -> None:
    stim_scale["value"] = float(value)
    for clamp, base_amp in clamp_specs:
        clamp.amp = stim_scale["value"] * base_amp


src = cnv.neuron.source(sections=sections, dt=0.025, display_dt=0.5)
display = src.segment_variable_display(
    "Morphology quantity",
    variables={
        "voltage": "v",
        "sodium activation (m)": "m_hh",
        "sodium inactivation (h)": "h_hh",
        "potassium gate (n)": "n_hh",
    },
    default="voltage",
    units={"voltage": "mV"},
    color_limits={
        "voltage": (-80.0, 50.0),
        "sodium activation (m)": (-0.05, 1.05),
        "sodium inactivation (h)": (-0.05, 1.05),
        "potassium gate (n)": (-0.05, 1.05),
    },
)
morph = src.morphology(
    variable="v",
    name="HH morphology",
    unit="mV",
    color_field_id=display.field_id,
    color_limits=(-80.0, 50.0),
    selected="soma@0.50000",
    max_refresh_hz=4.0,
)
volt = src.segment_variable_history(
    "Selected voltage",
    variables={"Voltage": "v"},
    y_label="Voltage",
    y_unit="mV",
    rolling_window=40.0,
    y_min=-85.0,
    y_max=55.0,
    series_colors={"Voltage": "#00d2be"},
)
gates = src.segment_variable_history(
    "Selected gating variables",
    variables={"m": "m_hh", "h": "h_hh", "n": "n_hh"},
    y_label="Gate value",
    rolling_window=40.0,
    y_min=-0.05,
    y_max=1.05,
    series_colors={"m": "#ff8c00", "h": "#ff50b4", "n": "#a000ff"},
)
current_data = src.record_refs(
    "Soma input current",
    refs=(clamp_specs[0][0]._ref_i,),
    series=("Input current",),
    unit="nA",
    window=40.0,
)
current = src.line(
    "Soma input current",
    source=current_data,
    rolling_window=40.0,
    y_label="Current",
    y_unit="nA",
    y_min=-0.4,
    y_max=1.8,
    pen="#2446a8",
)
src.control(
    "stim_scale",
    label="Stimulus scale",
    get=lambda: stim_scale["value"],
    set=set_stim_scale,
    min=0.0,
    max=1.6,
    presentation=cnv.ControlPresentationSpec(kind="slider", steps=160),
)
cnv.layout(((morph, volt), (gates, current), (src.controls_panel,)))

cnv.show(title="HH section inspector")

