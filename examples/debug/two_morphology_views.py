"""Two opt-in morphology panels over the same small NEURON model.

Requires: NEURON
Run: python examples/debug/two_morphology_views.py
"""

from __future__ import annotations

import os

# This smoke example intentionally shows two synchronized 3D panels. The global
# default stays conservative for heavier apps that should budget 3D redraw work.
os.environ.setdefault("CNV_MAX_VIEW_3D_REFRESHES_PER_FLUSH", "2")

from neuron import h

import compneurovis as cnv


def section(name: str, start: tuple[float, float, float], end: tuple[float, float, float]):
    sec = h.Section(name=name)
    sec.L = 80.0
    sec.diam = 4.0
    sec.nseg = 5
    sec.pt3dclear()
    sec.pt3dadd(*start, 4.0)
    sec.pt3dadd(*end, 4.0)
    sec.insert("hh")
    return sec


soma = section("soma", (-20.0, 0.0, 0.0), (20.0, 0.0, 0.0))
dend = section("dend", (20.0, 0.0, 0.0), (100.0, 25.0, 0.0))
dend.connect(soma(1.0))

# Keep a regular stimulus train visible in both morphology panels. A single early
# pulse is easy to miss in a live debug view.
clamps = []
for delay in range(25, 1000, 80):
    clamp = h.IClamp(soma(0.5))
    clamp.delay = float(delay)
    clamp.dur = 6.0
    clamp.amp = 0.8
    clamps.append(clamp)

# The source backend is paced by the Qt timer; this advances 0.5 sim-ms per
# frontend frame, slow enough to inspect the morphology voltage changes.
src = cnv.neuron.source(sections=[soma, dend], dt=0.025, display_dt=0.5)
left = src.morphology(variable="v", name="Voltage A", unit="mV", color_limits=(-80.0, 50.0))
right = src.morphology(variable="v", name="Voltage B", unit="mV", color_limits=(-80.0, 50.0), color_map="fire")
cnv.layout(((left, right),))

cnv.show(title="Two morphology views")
