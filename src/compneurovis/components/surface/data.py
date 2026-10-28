from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from compneurovis.core.field import Field


@dataclass(slots=True)
class SurfaceSceneData:
    field_id: str
    x_dim: str
    y_dim: str
    x_grid: np.ndarray
    y_grid: np.ndarray
    z: np.ndarray
    coords: dict[str, np.ndarray]


def surface_scene_from_field(field: Field) -> SurfaceSceneData:
    """Build surface scene data from the field that owns its grid coordinates."""
    y_dim, x_dim = field.dims[0], field.dims[1]
    y_coords = field.coord(y_dim)
    x_coords = field.coord(x_dim)

    if field.dims != (y_dim, x_dim):
        axis_map = {dim: idx for idx, dim in enumerate(field.dims)}
        z = np.transpose(field.values, axes=(axis_map[y_dim], axis_map[x_dim]))
    else:
        z = field.values

    x_grid, y_grid = np.meshgrid(np.asarray(x_coords, dtype=np.float32), np.asarray(y_coords, dtype=np.float32))
    return SurfaceSceneData(
        field_id=field.id,
        x_dim=x_dim,
        y_dim=y_dim,
        x_grid=x_grid,
        y_grid=y_grid,
        z=np.asarray(z, dtype=np.float32),
        coords={
            x_dim: np.asarray(x_coords, dtype=np.float32),
            y_dim: np.asarray(y_coords, dtype=np.float32),
        },
    )
