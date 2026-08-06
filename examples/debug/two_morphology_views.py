"""Two opt-in morphology panels over the same small NEURON model.

Requires: NEURON
Run: python examples/debug/two_morphology_views.py
"""

from __future__ import annotations

import os

# This smoke example intentionally shows two synchronized 3D panels. The global
# defaults stay conservative for heavier apps; this diagnostic opts into enough
# frontend budget to repaint both small canvases in the same step.
os.environ.setdefault("CNV_MAX_VIEW_3D_REFRESHES_PER_FLUSH", "2")
os.environ.setdefault("CNV_FRONTEND_STEP_SOFT_BUDGET_MS", "40")

from neuron import h  # noqa: E402 - environment must be configured before Qt imports

import compneurovis as cnv  # noqa: E402 - environment must be configured before Qt imports


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

# Keep a regular stimulus train visible in both morphology panels. With
# display_dt=0.5 ms and a 60 Hz backend tick, 45 sim-ms is about 1.5 seconds
# of wall time. The train lasts about 8 minutes of ordinary inspection.
PULSE_INTERVAL_MS = 45.0
PULSE_COUNT = 320

clamps = []
for pulse_index in range(PULSE_COUNT):
    clamp = h.IClamp(soma(0.5))
    clamp.delay = 25.0 + pulse_index * PULSE_INTERVAL_MS
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
