"""Multiple 3-D surface panels declared from one inline source.

Run: python examples/debug/multi_3d_views.py
"""

from __future__ import annotations

import numpy as np

import compneurovis as cnv


x = np.linspace(-2.5, 2.5, 80, dtype=np.float32)
y = np.linspace(-2.5, 2.5, 80, dtype=np.float32)
X, Y = np.meshgrid(x, y)
z1 = (np.sin(X * 2.0) + np.cos(Y * 2.0)).astype(np.float32)
z2 = (np.exp(-(X**2 + Y**2) / 2.5) * 2.0 - 1.0).astype(np.float32)

src = cnv.source()
left = src.surface("Wave surface", values=z1, x=x, y=y, color_map="bwr", camera_distance=55.0)
right = src.surface("Bump surface", values=z2, x=x, y=y, color_map="viridis", camera_distance=55.0)
cnv.layout(((left, right),))

cnv.show(title="Multi 3D view demo")
