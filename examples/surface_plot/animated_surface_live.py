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


def current_surface() -> np.ndarray:
    return (
        np.sin(2.2 * X + phase["value"])
        + 0.7 * np.cos(1.8 * Y - 0.7 * phase["value"])
        + 0.2 * np.sin(X * Y + 0.3 * phase["value"])
    ).astype(np.float32)


def step(ctx) -> None:
    phase["value"] += phase["speed"]


src = cnv.source(step)
src.control(
    "speed",
    label="Animation speed",
    get=lambda: phase["speed"],
    set=lambda ctx, value: phase.__setitem__("speed", float(value)),
    min=0.0,
    max=0.25,
    presentation=cnv.ControlPresentationSpec(kind="slider", steps=100),
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
