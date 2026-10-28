"""Small dependency-free spherical morphology-brush example."""

from __future__ import annotations

import numpy as np

import compneurovis as cnv

from sphere_brush import MorphologySphereBrush


positions = np.asarray(
    [
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 8.0),
        (0.0, 0.0, 16.0),
        (-7.0, 0.0, 23.0),
        (-14.0, 0.0, 30.0),
        (7.0, 0.0, 23.0),
        (14.0, 0.0, 30.0),
        (0.0, -7.0, 23.0),
        (0.0, -14.0, 30.0),
        (0.0, 7.0, 23.0),
        (0.0, 14.0, 30.0),
    ],
    dtype=np.float32,
)
count = len(positions)
entity_ids = tuple(f"segment-{index}" for index in range(count))
geometry = cnv.MorphologyGeometry(
    id="sphere_brush_test_morphology",
    positions=positions,
    orientations=np.asarray([np.eye(3)] * count, dtype=np.float32),
    radii=np.linspace(3.5, 1.5, count, dtype=np.float32),
    lengths=np.linspace(8.0, 5.0, count, dtype=np.float32),
    entity_ids=entity_ids,
    section_names=entity_ids,
    xlocs=np.full(count, 0.5, dtype=np.float32),
    labels=entity_ids,
)
paint_values = np.zeros(count, dtype=np.float32)

src = cnv.source()
brush_value = src.slider(
    "brush value",
    label="Paint value",
    min=0.0,
    max=1.0,
    default=0.75,
    send_to_backend=True,
)
brush_radius = src.slider(
    "brush radius",
    label="Brush radius",
    min=1.0,
    max=15.0,
    default=6.0,
    steps=56,
    send_to_backend=True,
)
brush_mode = src.checkbox(
    "sphere brush mode",
    label="Sphere brush mode",
    default=True,
)
morphology = src.morphology(
    geometry,
    name="Small sphere-brush test",
    values=paint_values,
    color_limits=(0.0, 1.0),
    color_map="viridis",
    selectable=True,
)
src.add(
    MorphologySphereBrush(
        morphology=morphology,
        geometry=geometry,
        initial_values=paint_values,
        brush_value=brush_value,
        brush_radius=brush_radius,
        enabled=brush_mode,
    )
)

cnv.layout(((morphology,), (src.controls_panel,)))
cnv.show(title="Small sphere-brush test")
