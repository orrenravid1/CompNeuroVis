"""Grid slice widget: cut a line profile through a static 2-D surface.

The surface is the same kind of plain data as ``surface.py``. The dropdown and
slider are frontend controls used by the grid-slice operator; no simulator or
backend-specific code is needed.

Run: python examples/widgets/grid_slice.py
"""

from __future__ import annotations

import numpy as np

import compneurovis as cnv


x = np.linspace(-3.0, 3.0, 120, dtype=np.float32)
y = np.linspace(-3.0, 3.0, 120, dtype=np.float32)
xx, yy = np.meshgrid(x, y)

field = np.exp(-0.5 * ((xx / 1.2) ** 2 + (yy / 1.2) ** 2))
field += 0.25 * np.exp(-0.5 * (((xx - 1.6) / 0.7) ** 2 + ((yy + 1.1) / 0.55) ** 2))
field = field.astype(np.float32)

src = cnv.source()
axis = src.dropdown("slice_axis", label="Slice axis", options=("x", "y"), default="x")
position = src.slider("slice_position", label="Slice position", min=0.0, max=1.0, default=0.5, steps=100)

surface = src.surface(
    "Activation landscape",
    values=field,
    x=x,
    y=y,
    unit="a.u.",
    color_map="aquamarine",
    color_by="height",
    color_limits=(0.0, 1.05),
    surface_shading="lit",
    render_axes=True,
    axes_in_middle=False,
    axis_labels=("x", "y", "activation"),
    background_color="white",
    camera_distance=18.0,
    camera_elevation=55.0,
    camera_azimuth=35.0,
)

profile = src.grid_slice(
    "Slice profile",
    surface=surface,
    axis=axis,
    position=position,
    overlay={"color": "#111111", "alpha": 0.95, "fill_alpha": 0.08, "width": 3.0},
    x_label="Position",
    y_label="Activation",
    y_unit="a.u.",
    y_min=0.0,
    y_max=1.1,
    color="#111111",
    linewidth=2.5,
    background_color="white",
)

cnv.layout(((surface,), (profile,), (src.controls_panel,)))

cnv.show(title="Grid slice widget")
