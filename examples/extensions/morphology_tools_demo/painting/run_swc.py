"""Paint the SWC morphology used by the NEURON complete-interface example."""

from __future__ import annotations

from pathlib import Path

import numpy as np

import compneurovis as cnv
from compneurovis.backends.neuron.geometry import build_morphology_geometry
from compneurovis.backends.neuron.io import load_swc_neuron

from morphology_painting import MorphologyPainting


repo_root = Path(__file__).resolve().parents[4]
swc_path = repo_root / "res" / "Animal_2_Basal_2.CNG.swc"
if not swc_path.is_file():
    raise FileNotFoundError(f"SWC file not found: {swc_path}")

sections = load_swc_neuron(str(swc_path))
geometry = build_morphology_geometry(sections)
paint_values = np.zeros(len(geometry.entity_ids), dtype=np.float32)

src = cnv.source()
brush = src.slider(
    "brush value",
    label="Paint value",
    min=0.0,
    max=1.0,
    default=0.75,
    send_to_backend=True,
)
paint_mode = src.checkbox(
    "paint mode",
    label="Paint instead of rotate",
    default=False,
)
morphology = src.morphology(
    geometry,
    name="Paint complete-interface SWC",
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
cnv.show(title="SWC morphology painting")
