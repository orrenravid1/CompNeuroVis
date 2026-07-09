"""Surface widget: a 2-D scalar field rendered as a shaded 3-D surface.

``surface(values=...)`` takes the grid outright; ``read=lambda: ...`` resamples it
every tick for a live surface. Here: membrane potential along an axon as an
action potential propagates, so the crest runs diagonally through space-time.

Run: python examples/widgets/surface.py
"""

from __future__ import annotations

import numpy as np

import compneurovis as cnv


V_REST_MV = -68.0
V_PEAK_MV = 38.0
CONDUCTION_VELOCITY_UM_PER_MS = 55.0
SPIKE_WIDTH_MS = 1.1
AFTER_HYPERPOLARIZATION_MV = 12.0

distance_um = np.linspace(0.0, 800.0, 220, dtype=np.float32)
time_ms = np.linspace(0.0, 22.0, 220, dtype=np.float32)
distance, time = np.meshgrid(distance_um, time_ms)

# Time each point of the axon is reached by the travelling wave.
arrival_ms = 2.0 + distance / CONDUCTION_VELOCITY_UM_PER_MS
lag_ms = time - arrival_ms

spike = np.exp(-0.5 * (lag_ms / SPIKE_WIDTH_MS) ** 2)
undershoot = np.exp(-0.5 * ((lag_ms - 2.4 * SPIKE_WIDTH_MS) / (2.2 * SPIKE_WIDTH_MS)) ** 2)
voltage = V_REST_MV + (V_PEAK_MV - V_REST_MV) * spike - AFTER_HYPERPOLARIZATION_MV * undershoot

membrane = cnv.source().surface(
    "Propagating action potential",
    values=voltage.astype(np.float32),
    x=distance_um,
    y=time_ms,
    unit="mV",
    color_map="fire",
    color_by="height",
    surface_shading="lit",
    render_axes=True,
    axes_in_middle=False,
    axis_labels=("distance (um)", "time (ms)", "Vm (mV)"),
    background_color="white",
    camera_distance=140.0,
    camera_elevation=32.0,
    camera_azimuth=42.0,
)

cnv.layout(((membrane,),))

cnv.show(title="Surface - propagating action potential")
