"""Two live line plots declared from one inline source.

Run: python examples/debug/two_line_plots.py
"""

from __future__ import annotations

import math

import compneurovis as cnv


state = {"t": 0.0, "phase": 0.0}


def step(ctx) -> None:
    state["t"] += 1.0
    state["phase"] += 0.08


src = cnv.source(step)
osc_a = src.line(
    "Oscillator A",
    x=lambda: state["t"],
    read={"sin": lambda: math.sin(state["phase"]), "cos": lambda: math.cos(state["phase"])},
    rolling_window=300.0,
    y_min=-1.2,
    y_max=1.2,
    colors={"sin": "#1f77b4", "cos": "#ff7f0e"},
)
osc_b = src.line(
    "Oscillator B",
    x=lambda: state["t"],
    read={"slow": lambda: math.sin(0.35 * state["phase"]), "fast": lambda: math.sin(2.0 * state["phase"])},
    rolling_window=300.0,
    y_min=-1.2,
    y_max=1.2,
    colors={"slow": "#2ca02c", "fast": "#d62728"},
)

cnv.layout(((osc_a, osc_b),))

cnv.show(title="Two line plots")
