"""Single-cell NEURON morphology visualizer using source-level inline authoring.

Requires: NEURON, res/Animal_2_Basal_2.CNG.swc
Run: python examples/neuron/complex_cell_example.py
"""

from __future__ import annotations

import os

from neuron import h

import compneurovis as cnv
from compneurovis.backends.neuron.utils import load_swc_neuron


curr_path = os.path.dirname(os.path.abspath(__file__))
swc_path = os.path.join(curr_path, "..", "..", "res", "Animal_2_Basal_2.CNG.swc")
sections = load_swc_neuron(swc_path)
for sec in sections:
    sec.insert("hh")
    if "soma" not in sec.name().lower():
        sec.nseg = 10

soma = next(sec for sec in sections if "soma" in sec.name().lower())
stim_amp = {"value": 1.0}
iclamps = []
for delay, dur, amp in [(2, 5, 1), (20, 5, 1), (40, 5, 1), (60, 5, 1), (80, 5, 1)]:
    clamp = h.IClamp(soma(0.5))
    clamp.delay = delay
    clamp.dur = dur
    clamp.amp = stim_amp["value"] * amp
    iclamps.append((clamp, amp))


def set_stim_amp(ctx, value: float) -> None:
    stim_amp["value"] = float(value)
    for clamp, base_amp in iclamps:
        clamp.amp = stim_amp["value"] * base_amp


src = cnv.neuron.source(sections=sections, dt=0.25, display_dt=0.25)
morph = src.morphology(variable="v", name="Voltage", unit="mV", color_limits=(-80.0, 50.0), selected=f"{soma.name()}@0.50000")
volt = src.line("Selected voltage", source=morph.selection, y_label="Voltage", y_unit="mV", rolling_window=120.0, y_min=-85.0, y_max=55.0)
src.slider(
    "stim_amp",
    label="Stimulus amplitude (nA)",
    get=lambda: stim_amp["value"],
    set=set_stim_amp,
    min=0.0,
    max=2.0,
)

cnv.layout(((morph, volt), (src.controls_panel,)))

cnv.show(title="Complex cell viewer")
