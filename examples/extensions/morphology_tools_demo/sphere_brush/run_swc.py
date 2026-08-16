"""Paint the complete-interface SWC with a variable-radius 3-D sphere brush."""

from __future__ import annotations

from pathlib import Path

import numpy as np

import compneurovis as cnv
from compneurovis.backends.neuron.geometry import build_morphology_geometry
from compneurovis.backends.neuron.io import load_swc_neuron

from sphere_brush import MorphologySphereBrush


repo_root = Path(__file__).resolve().parents[4]
swc_path = repo_root / "res" / "Animal_2_Basal_2.CNG.swc"
if not swc_path.is_file():
    raise FileNotFoundError(f"SWC file not found: {swc_path}")

geometry = build_morphology_geometry(load_swc_neuron(str(swc_path)))
paint_values = np.zeros(len(geometry.entity_ids), dtype=np.float32)

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
    label="Brush radius (µm)",
    min=0.25,
    max=30.0,
    default=5.0,
    steps=119,
    send_to_backend=True,
)
brush_mode = src.checkbox(
    "sphere brush mode",
    label="Sphere brush mode",
    default=False,
)
morphology = src.morphology(
    geometry,
    name="Sphere-brush SWC",
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
cnv.show(title="SWC sphere-brush painting")
