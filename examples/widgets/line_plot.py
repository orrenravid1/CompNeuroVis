"""Line plot widget: live traces from a tiny pure-Python signal generator.

No simulator is involved. The source steps one oscillator every frame and the
line widget samples two callables from that object.

Run: python examples/widgets/line_plot.py
"""

from __future__ import annotations

import math

import compneurovis as cnv


class Oscillator:
    def __init__(self) -> None:
        self.t_ms = 0.0
        self.signal = 0.0
        self.envelope = 1.0

    def step(self, ctx) -> None:
        del ctx
        self.t_ms += 8.0
        t_s = self.t_ms / 1000.0
        self.envelope = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(2.0 * math.pi * 0.35 * t_s))
        carrier = math.sin(2.0 * math.pi * 7.0 * t_s)
        self.signal = self.envelope * carrier


osc = Oscillator()
src = cnv.source(osc.step)

trace = src.line(
    "Live oscillator",
    read={"Signal": lambda: osc.signal, "Envelope": lambda: osc.envelope},
    x=lambda: osc.t_ms,
    x_label="Time",
    x_unit="ms",
    y_label="Amplitude",
    y_unit="a.u.",
    y_min=-1.1,
    y_max=1.1,
    rolling_window=1200.0,
    trim_to_rolling_window=True,
    colors={"Signal": "#2f6fed", "Envelope": "#d95f02"},
    linewidths={"Signal": 2.2, "Envelope": 2.0},
    linestyles={"Signal": "-", "Envelope": "--"},
    background_color="white",
)

cnv.layout(((trace,),))

cnv.show(title="Line plot widget")
