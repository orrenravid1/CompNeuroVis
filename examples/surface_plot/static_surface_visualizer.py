"""Static surface visualizer using source-level inline authoring.

Run: python examples/surface_plot/static_surface_visualizer.py
"""

from __future__ import annotations

import numpy as np

import compneurovis as cnv


COLOR_OPTIONS = ("black", "white", "gray", "red", "green", "blue", "orange", "purple")
COLOR_MODES = ("height", "uniform")
SHADING_MODES = ("unlit", "lit")


def choice(source, name: str, label: str, default: str, options: tuple[str, ...]):
    return source.control(
        name,
        label=label,
        value_spec=cnv.ChoiceValueSpec(default=default, options=options),
        presentation=cnv.ControlPresentationSpec(kind="dropdown"),
    )


def slider(source, name: str, label: str, default: float, min_value: float, max_value: float, steps: int):
    return source.control(
        name,
        label=label,
        value_spec=cnv.ScalarValueSpec(default=default, min=min_value, max=max_value),
        presentation=cnv.ControlPresentationSpec(kind="slider", steps=steps),
    )


x = np.linspace(-3.0, 3.0, 120, dtype=np.float32)
y = np.linspace(-3.0, 3.0, 120, dtype=np.float32)
X, Y = np.meshgrid(x, y)
R = np.sqrt(X**2 + Y**2)
Z = (np.sinc(R) * 2.0).astype(np.float32)

src = cnv.source()
color_by = choice(src, "color_by", "Coloring", "height", COLOR_MODES)
surface_color = choice(src, "surface_color", "Surface color", "blue", COLOR_OPTIONS)
surface_shading = choice(src, "surface_shading", "Shading", "unlit", SHADING_MODES)
axis_color = choice(src, "axis_color", "Axis color", "black", COLOR_OPTIONS)
text_color = choice(src, "text_color", "Text color", "black", COLOR_OPTIONS)
background_color = choice(src, "background_color", "Background", "white", COLOR_OPTIONS)
surface_alpha = slider(src, "surface_alpha", "Surface alpha", 0.9, 0.1, 1.0, 90)
tick_count = src.control(
    "tick_count",
    label="Axis ticks",
    value_spec=cnv.ScalarValueSpec(default=7, min=0, max=12, value_type="int"),
)
tick_length = slider(src, "tick_length_scale", "Tick length", 1.0, 0.0, 3.0, 120)
tick_label_size = slider(src, "tick_label_size", "Tick text size", 12.0, 6.0, 24.0, 90)
axis_label_size = slider(src, "axis_label_size", "Axis label size", 16.0, 8.0, 32.0, 96)
axis_alpha = slider(src, "axis_alpha", "Axes alpha", 1.0, 0.0, 1.0, 100)

surface = src.surface(
    "Interactive sinc surface",
    values=Z,
    x=x,
    y=y,
    color_map="bwr",
    color_by=color_by,
    surface_color=surface_color,
    surface_shading=surface_shading,
    render_axes=True,
    axes_in_middle=True,
    tick_count=tick_count,
    tick_length_scale=tick_length,
    tick_label_size=tick_label_size,
    axis_label_size=axis_label_size,
    axis_color=axis_color,
    text_color=text_color,
    axis_labels=("x", "y", "height"),
    background_color=background_color,
    surface_alpha=surface_alpha,
    axis_alpha=axis_alpha,
    camera_distance=120.0,
)

cnv.layout(((surface,), (src.controls_panel,)))

cnv.show(title="Interactive sinc surface")
