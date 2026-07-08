"""Surface cross-section visualizer using source-level inline authoring.

Run: python examples/surface_plot/surface_cross_section_visualizer.py
"""

from __future__ import annotations

import numpy as np

import compneurovis as cnv


def build_demo_surface():
    x = np.linspace(-4.0, 4.0, 180, dtype=np.float32)
    y = np.linspace(-3.0, 3.0, 160, dtype=np.float32)
    X, Y = np.meshgrid(x, y)
    Z = (
        0.9 * np.sin(1.4 * X)
        + 0.35 * X
        + 1.1 * np.cos(0.9 * Y)
        + 0.45 * np.sin(1.8 * Y + 0.5 * X)
        + 0.08 * X * Y
    ).astype(np.float32)
    return x, y, Z


x, y, z = build_demo_surface()
src = cnv.source()
axis = src.control(
    "slice_axis",
    label="Slice axis",
    value_spec=cnv.ChoiceValueSpec(default="x", options=("x", "y")),
    presentation=cnv.ControlPresentationSpec(kind="dropdown"),
)
position = src.control(
    "slice_position",
    label="Slice position",
    value_spec=cnv.ScalarValueSpec(default=0.0, min=0.0, max=1.0),
    presentation=cnv.ControlPresentationSpec(kind="slider", steps=200),
)

surface = src.surface(
    "Surface",
    values=z,
    x=x,
    y=y,
    color_map="bwr",
    render_axes=True,
    axes_in_middle=True,
    tick_count=7,
    axis_color="black",
    text_color="black",
    axis_labels=("x", "y", "height"),
    background_color="white",
    surface_alpha=0.9,
    axis_alpha=0.95,
    tick_length_scale=1.0,
    tick_label_size=12.0,
    axis_label_size=16.0,
    camera_distance=30.0,
)
section = src.grid_slice(
    "Cross section",
    surface=surface,
    axis=axis,
    position=position,
    overlay={"fill_alpha": 0.16},
    y_label="height",
    pen="#1f3c88",
    background_color="white",
)
cnv.layout(((surface, section), (src.controls_panel,)))

cnv.show(title="Surface cross-section viewer")
