"""Minimal live app — a sine wave over a custom Python step function.

The smallest inline app: a source whose step advances a clock, a single trace read
from a lambda, one slider, and pause/reset actions. No simulator backend.

Run: python examples/custom/sine_wave.py
"""
import math

import compneurovis as cnv

DT_MS = 16.0
FREQ_HZ = 0.5

t_ms = [0.0]
freq_hz = [FREQ_HZ]
paused = [False]


def _step(ctx):
    if not paused[0]:
        t_ms[0] += DT_MS


sim = cnv.source(_step)

sim.line(
    "Sine wave",
    read=lambda: math.sin(2 * math.pi * freq_hz[0] * t_ms[0] / 1000.0),
    x=lambda: t_ms[0],
    y_min=-1.1,
    y_max=1.1,
)

sim.slider("freq_hz", label="Frequency (Hz)",
            get=lambda: freq_hz[0],
            set=lambda ctx, v: freq_hz.__setitem__(0, v),
            min=0.1, max=5.0)

sim.button("pause", label="Pause / Resume",
           fn=lambda ctx: paused.__setitem__(0, not paused[0]))
sim.button("reset", label="Reset",
           fn=lambda ctx: (t_ms.__setitem__(0, 0.0), ctx.reset()))

cnv.show()
