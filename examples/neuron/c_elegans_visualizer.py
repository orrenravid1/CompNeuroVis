"""C. elegans morphology visualizer using source-level inline authoring.

Requires: NEURON, res/celegans_cells_swc/
Run: python examples/neuron/c_elegans_visualizer.py
"""

from __future__ import annotations

import os
import random

from neuron import h

import compneurovis as cnv
from compneurovis.backends.neuron.io import load_swc_multi


curr_path = os.path.dirname(os.path.abspath(__file__))
swc_path = os.path.join(curr_path, "..", "..", "res", "celegans_cells_swc")
sections = []
for swc_file in os.listdir(swc_path):
    print(f"Loading cell {swc_file}")
    cell_name = swc_file.split(".")[0]
    trees = load_swc_multi(os.path.join(swc_path, swc_file), cell_name)
    for section_list in trees.values():
        sections.extend(section_list)

for sec in sections:
    sec.insert("hh")
    if "soma" not in sec.name().lower():
        sec.nseg = 10

iclamps = []
for soma in [sec for sec in sections if "soma" in sec.name().lower()]:
    for delay, dur, amp in [
        (2 + random.random() * 5, 5, 0.2),
        (20 + random.random() * 5, 5, 0.2),
        (40 + random.random() * 5, 5, 0.2),
        (60 + random.random() * 5, 5, 0.2),
        (80 + random.random() * 5, 5, 0.2),
    ]:
        clamp = h.IClamp(soma(0.5))
        clamp.delay = delay
        clamp.dur = dur
        clamp.amp = amp
        iclamps.append(clamp)

src = cnv.neuron.source(sections=sections, dt=0.025, display_dt=0.5)
morph = src.morphology(variable="v", name="Voltage", unit="mV", color_limits=(-80.0, 50.0))
volt = src.line(
    "Selected voltage",
    source=morph.selection,
    y_label="Voltage",
    y_unit="mV",
    rolling_window=500.0,
    y_min=-85.0,
    y_max=55.0,
)
cnv.layout(((morph, volt),))

cnv.show(title="C. elegans morphology viewer")
