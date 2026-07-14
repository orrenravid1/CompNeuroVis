from __future__ import annotations

from typing import Any

import numpy as np

from compneurovis.core.field import Field
from compneurovis.core.operators import GridSliceOperatorSpec
from compneurovis.frontends.vispy.view_inputs.surface import SurfaceSceneData


def resolve_grid_slice_position(
    coords: dict[str, np.ndarray],
    *,
    axis_value_key: str | None,
    position_value_key: str | None,
    values: dict[str, Any],
    default_axis: str,
):
    if not axis_value_key or not position_value_key:
        return None
    axis = values.get(axis_value_key, default_axis)
    if axis not in coords:
        axis = default_axis if default_axis in coords else next(iter(coords))
    normalized = min(1.0, max(0.0, float(values.get(position_value_key, 0.0))))
    axis_coords = np.asarray(coords[axis], dtype=np.float32)
    idx = max(0, min(len(axis_coords) - 1, int(round(normalized * (len(axis_coords) - 1)))))
    return axis, idx, float(axis_coords[idx])


def overlay_from_grid_slice_operator(
    surface_scene: SurfaceSceneData,
    operator: GridSliceOperatorSpec,
    resolved_values: dict[str, Any],
):
    resolved = resolve_grid_slice_position(
        surface_scene.coords,
        axis_value_key=operator.axis_value_key,
        position_value_key=operator.position_value_key,
        values=resolved_values,
        default_axis=surface_scene.x_dim,
    )
    if resolved is None:
        return None
    axis, _idx, value = resolved
    return {
        "operator_id": operator.id,
        "axis": "x" if axis == surface_scene.x_dim else "y",
        "value": value,
        "color": resolved_values[f"{operator.id}:color"],
        "alpha": resolved_values[f"{operator.id}:alpha"],
        "fill_alpha": resolved_values[f"{operator.id}:fill_alpha"],
        "width": resolved_values[f"{operator.id}:width"],
    }


def line_from_grid_slice_operator(field: Field, operator: GridSliceOperatorSpec, values: dict[str, Any]):
    if field.values.ndim != 2:
        raise ValueError("grid slice operators require a 2D field")
    resolved = resolve_grid_slice_position(
        {dim: field.coord(dim) for dim in field.dims},
        axis_value_key=operator.axis_value_key,
        position_value_key=operator.position_value_key,
        values=values,
        default_axis=field.dims[-1],
    )
    if resolved is None:
        return None
    slice_dim, idx, slice_value = resolved
    other_dims = [dim for dim in field.dims if dim != slice_dim]
    if len(other_dims) != 1:
        raise ValueError("grid slice operators require exactly one non-sliced dimension")
    x_dim = other_dims[0]
    sliced = field.select({slice_dim: idx})
    return (
        np.asarray(sliced.coord(x_dim), dtype=np.float32),
        np.asarray(sliced.values, dtype=np.float32),
        x_dim,
        slice_dim,
        slice_value,
    )


def field_from_grid_slice_operator(
    field: Field, operator: GridSliceOperatorSpec, values: dict[str, Any]
) -> Field | None:
    result = line_from_grid_slice_operator(field, operator, values)
    if result is None:
        return None
    x, y, x_dim, slice_dim, slice_value = result
    return Field(
        id=f"{field.id} at {slice_dim}={slice_value:.3f}",
        values=y,
        dims=(x_dim,),
        coords={x_dim: x},
    )
