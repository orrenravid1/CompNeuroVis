"""Animated surface with a live, controllable cross-section.

The surface updates on every source step. The grid-slice widget operates on
that same live field, draws its overlay on the surface, and supplies the
current profile to the line plot.

Run: python examples/surface_plot/animated_surface_cross_section.py
"""

from __future__ import annotations

import numpy as np

import compneurovis as cnv


x = np.linspace(-3.0, 3.0, 100, dtype=np.float32)
y = np.linspace(-3.0, 3.0, 100, dtype=np.float32)
xx, yy = np.meshgrid(x, y)

state = {
    "phase": 0.0,
    "speed": 0.08,
    "amplitude_x": 1.0,
    "amplitude_y": 1.0,
    "frequency_x": 2.2,
    "frequency_y": 1.8,
}


def current_surface() -> np.ndarray:
    return (
        state["amplitude_x"]
        * np.sin(state["frequency_x"] * xx + state["phase"])
        + state["amplitude_y"]
        * np.cos(state["frequency_y"] * yy - 0.7 * state["phase"])
        + 0.5 * np.sin(xx * yy + 0.3 * state["phase"])
    ).astype(np.float32)


def step(ctx) -> None:
    del ctx
    state["phase"] += state["speed"]


def set_state(name: str):
    def update(ctx, value: float) -> None:
        del ctx
        state[name] = float(value)

    return update


src = cnv.source(step)
src.slider(
    "speed",
    label="Animation speed",
    get=lambda: state["speed"],
    set=set_state("speed"),
    min=0.0,
    max=0.25,
)
src.slider(
    "amplitude_x",
    label="X amplitude",
    get=lambda: state["amplitude_x"],
    set=set_state("amplitude_x"),
    min=0.0,
    max=2.0,
)
src.slider(
    "amplitude_y",
    label="Y amplitude",
    get=lambda: state["amplitude_y"],
    set=set_state("amplitude_y"),
    min=0.0,
    max=2.0,
)
src.slider(
    "frequency_x",
    label="X frequency",
    get=lambda: state["frequency_x"],
    set=set_state("frequency_x"),
    min=0.0,
    max=5.0,
)
src.slider(
    "frequency_y",
    label="Y frequency",
    get=lambda: state["frequency_y"],
    set=set_state("frequency_y"),
    min=0.0,
    max=5.0,
)

slice_axis = src.dropdown(
    "slice_axis",
    label="Slice axis",
    options=("x", "y"),
    default="x",
)
slice_position = src.slider(
    "slice_position",
    label="Slice position",
    min=0.0,
    max=1.0,
    default=0.5,
    steps=200,
)

surface = src.surface(
    "Animated surface",
    read=current_surface,
    x=x,
    y=y,
    color_map="bwr",
    color_limits=(-4.5, 4.5),
    render_axes=True,
    axes_in_middle=True,
    axis_labels=("x", "y", "height"),
    surface_alpha=0.92,
    camera_distance=30.0,
    max_refresh_hz=60
)

cross_section = src.grid_slice(
    "Animated cross section",
    surface=surface,
    axis=slice_axis,
    position=slice_position,
    overlay={
        "color": "#111111",
        "alpha": 0.95,
        "fill_alpha": 0.14,
        "width": 3.0,
    },
)

profile = src.line(
    "Live cross section",
    source=cross_section,
    x=None,
    x_label="Position",
    y_label="Height",
    y_min=-4.5,
    y_max=4.5,
    color="#1f3c88",
    linewidth=2.5,
    background_color="white",
    max_refresh_hz=30
)

cnv.layout(((surface, profile), (src.controls_panel,)))

cnv.show(title="Animated surface cross-section")
