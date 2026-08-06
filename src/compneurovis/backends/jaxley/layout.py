from __future__ import annotations

import numpy as np


def translate_cell_xyzr(cell, offset) -> None:
    delta = np.asarray(offset, dtype=np.float32)
    translated = []
    for branch_xyzr in cell.xyzr:
        coords = np.asarray(branch_xyzr, dtype=np.float32).copy()
        coords[:, :3] += delta[None, :]
        translated.append(coords)
    cell.xyzr = translated
    cell.compute_compartment_centers()


def translate_cells_xyzr(cells, offsets) -> None:
    for cell, offset in zip(cells, offsets):
        translate_cell_xyzr(cell, offset)
