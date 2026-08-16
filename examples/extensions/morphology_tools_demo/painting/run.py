"""Standalone morphology-painting example."""

from __future__ import annotations

import numpy as np

import compneurovis as cnv

from morphology_painting import MorphologyPainting


def painting_geometry() -> cnv.MorphologyGeometry:
    positions = np.asarray(
        [
            (0.0, 0.0, 0.0),
            (0.0, 0.0, 2.5),
            (0.0, 0.0, 5.0),
            (-1.5, 0.0, 7.0),
            (-3.0, 0.0, 9.0),
            (-4.5, 0.0, 11.0),
            (1.5, 0.0, 7.0),
            (3.0, 0.0, 9.0),
            (4.5, 0.0, 11.0),
            (0.0, -1.5, 7.0),
            (0.0, -3.0, 9.0),
            (0.0, 1.5, 7.0),
            (0.0, 3.0, 9.0),
        ],
        dtype=np.float32,
    ) * 10.0
    count = len(positions)
    entity_ids = tuple(f"segment-{index}" for index in range(count))
    return cnv.MorphologyGeometry(
        id="paintable_morphology",
        positions=positions,
        orientations=np.asarray([np.eye(3)] * count, dtype=np.float32),
        radii=np.linspace(12.5, 3.5, count, dtype=np.float32),
        lengths=np.linspace(25.0, 14.0, count, dtype=np.float32),
        entity_ids=entity_ids,
        section_names=entity_ids,
        xlocs=np.full(count, 0.5, dtype=np.float32),
        labels=entity_ids,
    )


geometry = painting_geometry()
paint_values = np.zeros(len(geometry.entity_ids), dtype=np.float32)

src = cnv.source()
brush = src.slider(
    "brush value",
    label="Paint value",
    min=0.0,
    max=1.0,
    default=0.75,
    # Painting runs in the source backend, so its brush dependency must cross
    # the frontend/backend boundary even though it has no standalone setter.
    send_to_backend=True,
)
paint_mode = src.checkbox(
    "paint mode",
    label="Paint instead of rotate",
    default=False,
)
morphology = src.morphology(
    geometry,
    name="Paint morphology",
    values=paint_values,
    color_limits=(0.0, 1.0),
    color_map="viridis",
    selectable=True,
)
src.add(
    MorphologyPainting(
        morphology=morphology,
        entity_ids=geometry.entity_ids,
        initial_values=paint_values,
        brush_value=brush,
        enabled=paint_mode,
    )
)

cnv.layout(((morphology,), (src.controls_panel,)))
cnv.show(title="Standalone morphology painting")
