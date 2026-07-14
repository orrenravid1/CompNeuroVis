"""Surface widget: a simple smooth 2-D field rendered as a 3-D surface.

This is intentionally conceptual: one activation hill over a square sheet. It is
meant to show the surface widget itself, not a simulator or domain model.

Run: python examples/widgets/surface.py
"""

from __future__ import annotations

import numpy as np

import compneurovis as cnv


x = np.linspace(-3.0, 3.0, 96, dtype=np.float32)
y = np.linspace(-3.0, 3.0, 96, dtype=np.float32)
xx, yy = np.meshgrid(x, y)

activation = np.exp(-0.5 * ((xx / 1.15) ** 2 + (yy / 1.15) ** 2))
activation += 0.18 * np.exp(-0.5 * (((xx + 1.55) / 0.55) ** 2 + ((yy - 1.25) / 0.75) ** 2))
activation = activation.astype(np.float32)

surface = cnv.source().surface(
    "Activation landscape",
    values=activation,
    x=x,
    y=y,
    unit="a.u.",
    color_map="aquamarine",
    color_by="height",
    color_limits=(0.0, 1.05),
    surface_shading="lit",
    render_axes=True,
    axes_in_middle=False,
    tick_count=5,
    axis_labels=("x", "y", "activation"),
    background_color="white",
    camera_distance=18.0,
    camera_elevation=55.0,
    camera_azimuth=35.0,
)

cnv.layout(((surface,),))

cnv.show(title="Surface widget")
