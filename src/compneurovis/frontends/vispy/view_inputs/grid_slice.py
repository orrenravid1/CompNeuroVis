from __future__ import annotations

from typing import Any

import numpy as np

from compneurovis.core.field import Field
from compneurovis.core.operators import GridSliceOperatorSpec
from compneurovis.frontends.vispy.operator_adapters import register_operator_adapter
from compneurovis.frontends.vispy.refresh_planning import (
    RefreshTarget,
    _binding_matches,
    _optional_ref,
    _ref,
    _value_key_matches,
)
from compneurovis.frontends.vispy.view_inputs.surface import SurfaceSceneData

# The refresh target this operator contributes to the surface panel it cuts. The
# grid slice owns this name (it produces the overlay); the surface visual renders it.
OPERATOR_OVERLAY = "operator_overlay"


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


class _GridSliceAdapter:
    """The grid-slice operator's whole frontend contract, in the slice's own module.

    Refresh routing: the operator draws its cut line as an overlay in the surface
    panel, matching a surface view when its source field (and, if set, geometry) is
    the surface's, and routing the relevant change to an ``operator_overlay`` target.
    Data resolution: ``resolve_field`` computes the sliced profile a consuming view
    reads. The planner/frontend dispatch here by ``type(op)`` -- they hold no
    grid-slice knowledge.
    """

    # Props that carry ValueBindingSpec references (live appearance of the cut line).
    _VALUE_BINDING_PROPS = frozenset({"color", "alpha", "fill_alpha", "width"})
    # Props whose change alters the operator's computed output (its sampled slice),
    # so a view consuming the operator as a data input must refresh.
    _COMPUTE_PROPS = frozenset({"field_id", "geometry_id",
                                "axis_value_key", "position_value_key"})

    def _geom_compatible(self, ctx) -> bool:
        return _optional_ref(ctx.op.geometry_id, ctx.op_ref.fragment_id) in {
            None,
            _optional_ref(getattr(ctx.view, "geometry_id", None), ctx.view_ref.fragment_id),
        }

    def _slices_view(self, ctx) -> bool:
        view_field = getattr(ctx.view, "field_id", None)
        if view_field is None:
            return False
        return (
            _ref(ctx.op.field_id, ctx.op_ref.fragment_id)
            == _ref(view_field, ctx.view_ref.fragment_id)
            and self._geom_compatible(ctx)
        )

    def on_value_change(self, ctx, value_key) -> set:
        if not self._slices_view(ctx):
            return set()
        op, frag = ctx.op, ctx.op_ref.fragment_id
        if (
            any(_binding_matches(getattr(op, p, None), value_key, frag) for p in self._VALUE_BINDING_PROPS)
            or _value_key_matches(op.axis_value_key, value_key, frag)
            or _value_key_matches(op.position_value_key, value_key, frag)
        ):
            return {RefreshTarget(OPERATOR_OVERLAY, ctx.view_id)}
        return set()

    def on_field_replace(self, ctx, field_ref) -> set:
        # The overlay recomputes when the *replaced* field is the one the slice
        # samples (and its geometry matches this surface).
        if getattr(ctx.view, "field_id", None) is None:
            return set()
        if (
            _ref(ctx.op.field_id, ctx.op_ref.fragment_id) == field_ref
            and self._geom_compatible(ctx)
        ):
            return {RefreshTarget(OPERATOR_OVERLAY, ctx.view_id)}
        return set()

    def on_operator_patch(self, ctx, changed_props) -> set:
        # Any patch to a slice that cuts this surface repaints its overlay.
        if self._slices_view(ctx):
            return {RefreshTarget(OPERATOR_OVERLAY, ctx.view_id)}
        return set()

    def affects_output(self, changed_props) -> bool:
        return bool(changed_props & self._COMPUTE_PROPS)

    def output_field_deps(self, op, fragment_id) -> tuple:
        # A view consuming the slice as data depends on the field the slice samples.
        return (op.field_id,)

    def output_binds_value(self, op, value_key, fragment_id) -> bool:
        # The slice output tracks its axis/position controls.
        return _value_key_matches(op.axis_value_key, value_key, fragment_id) or _value_key_matches(
            op.position_value_key, value_key, fragment_id
        )

    def resolve_field(self, op, get_field, values) -> Field | None:
        # An extension view consuming the slice reads its computed profile: sample
        # the operator's source field at the current axis/position. ``get_field``
        # fetches a source field id (the frontend keeps that lookup to itself).
        source = get_field(op.field_id)
        if source is None:
            return None
        return field_from_grid_slice_operator(source, op, values)


register_operator_adapter(GridSliceOperatorSpec, _GridSliceAdapter())
