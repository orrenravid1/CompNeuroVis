"""Live animated surface using source-level inline authoring.

Run: python examples/surface_plot/animated_surface_live.py
"""

from __future__ import annotations

import numpy as np

import compneurovis as cnv


x = np.linspace(-3.0, 3.0, 100, dtype=np.float32)
y = np.linspace(-3.0, 3.0, 100, dtype=np.float32)
X, Y = np.meshgrid(x, y)
phase = {"value": 0.0, "speed": 0.08}
amplitude_X = 1.0
amplitude_Y = 1.0
frequency_X = 2.2
frequency_Y = 1.8

def set_amplitude_X(ctx, value: float) -> None:
    global amplitude_X
    amplitude_X = value
def set_amplitude_Y(ctx, value: float) -> None:
    global amplitude_Y
    amplitude_Y = value
def set_frequency_X(ctx, value: float) -> None:
    global frequency_X
    frequency_X = value
def set_frequency_Y(ctx, value: float) -> None:
    global frequency_Y
    frequency_Y = value

def current_surface() -> np.ndarray:
    return (
        np.sin(frequency_X * X + phase["value"])
        + amplitude_X * np.cos(frequency_Y * Y - 0.7 * phase["value"])
        + amplitude_Y * np.sin(X * Y + 0.3 * phase["value"])
    ).astype(np.float32)


def step(ctx) -> None:
    phase["value"] += phase["speed"]


src = cnv.source(step)
src.slider(
    "speed",
    label="Animation speed",
    get=lambda: phase["speed"],
    set=lambda ctx, value: phase.__setitem__("speed", float(value)),
    min=0.0,
    max=0.25,
)
src.slider(
    "amplitudeX",
    label="Amplitude X",
    get=lambda: amplitude_X,
    set=set_amplitude_X,
    min=0.0,
    max=2.0,
)
src.slider(
    "amplitudeY",
    label="Amplitude Y",
    get=lambda: amplitude_Y,
    set=set_amplitude_Y,
    min=0.0,
    max=2.0,
)
src.slider(
    "frequencyX",
    label="Frequency X",
    get=lambda: frequency_X,
    set=set_frequency_X,
    min=0.0,
    max=5.0,
)
src.slider(
    "frequencyY",
    label="Frequency Y",
    get=lambda: frequency_Y,
    set=set_frequency_Y,
    min=0.0,
    max=5.0,
)

surface = src.surface(
    "Animated surface",
    read=current_surface,
    x=x,
    y=y,
    color_map="bwr",
    color_limits=(-2.0, 2.0),
    render_axes=True,
    axis_labels=("x", "y", "height"),
    surface_alpha=0.95,
    camera_distance=70.0,
)

cnv.layout(((surface,), (src.controls_panel,)))

cnv.show(title="Animated surface")
