from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from compneurovis.core.field import Field
from compneurovis.core.operators import ExtensionOperatorSpec
from compneurovis.frontends.vispy.operator_adapters import register_operator_adapter
from compneurovis.frontends.vispy.refresh_planning import RefreshTarget
from compneurovis.frontends.vispy.view_inputs.bindings import (
    _binding_matches,
    _ref,
    resolve_binding,
)
from compneurovis.frontends.vispy.view_inputs.surface import SurfaceSceneData

GRID_SLICE_OPERATOR_KIND = "grid_slice"
OPERATOR_OVERLAY = "operator_overlay"


@dataclass(frozen=True, slots=True)
class GridSliceOperatorConfig:
    """Frontend-local typed interpretation of a neutral grid-slice operator."""

    id: str
    field_id: str
    axis: Any = "x"
    position: Any = 0.0
    color: Any = "#111111"
    alpha: Any = 0.95
    fill_alpha: Any = 0.0
    width: Any = 3.0

    @classmethod
    def from_extension(
        cls,
        operator: ExtensionOperatorSpec,
    ) -> "GridSliceOperatorConfig":
        if operator.kind != GRID_SLICE_OPERATOR_KIND:
            raise ValueError(
                f"Expected {GRID_SLICE_OPERATOR_KIND!r}, got {operator.kind!r}"
            )
        properties = operator.properties
        return cls(
            id=operator.id,
            field_id=operator.inputs.get("field", ""),
            axis=properties.get("axis", "x"),
            position=properties.get("position", 0.0),
            color=properties.get("color", "#111111"),
            alpha=properties.get("alpha", 0.95),
            fill_alpha=properties.get("fill_alpha", 0.0),
            width=properties.get("width", 3.0),
        )

    def resolved(
        self,
        values: dict[Any, Any],
        fragment_id: str,
    ) -> "GridSliceOperatorConfig":
        return replace(
            self,
            axis=resolve_binding(self.axis, values, fragment_id),
            position=resolve_binding(self.position, values, fragment_id),
            color=resolve_binding(self.color, values, fragment_id),
            alpha=resolve_binding(self.alpha, values, fragment_id),
            fill_alpha=resolve_binding(self.fill_alpha, values, fragment_id),
            width=resolve_binding(self.width, values, fragment_id),
        )


def grid_slice_config(
    operator: ExtensionOperatorSpec,
) -> GridSliceOperatorConfig:
    return GridSliceOperatorConfig.from_extension(operator)


def resolve_grid_slice_position(
    coords: dict[str, np.ndarray],
    *,
    axis: Any,
    position: Any,
    default_axis: str,
):
    resolved_axis = str(axis)
    if resolved_axis not in coords:
        resolved_axis = default_axis if default_axis in coords else next(iter(coords))
    normalized = min(1.0, max(0.0, float(position)))
    axis_coords = np.asarray(coords[resolved_axis], dtype=np.float32)
    idx = max(
        0,
        min(
            len(axis_coords) - 1,
            int(round(normalized * (len(axis_coords) - 1))),
        ),
    )
    return resolved_axis, idx, float(axis_coords[idx])


def overlay_from_grid_slice_operator(
    surface_scene: SurfaceSceneData,
    operator: GridSliceOperatorConfig,
):
    axis, _idx, value = resolve_grid_slice_position(
        surface_scene.coords,
        axis=operator.axis,
        position=operator.position,
        default_axis=surface_scene.x_dim,
    )
    return {
        "operator_id": operator.id,
        "axis": "x" if axis == surface_scene.x_dim else "y",
        "value": value,
        "color": operator.color,
        "alpha": operator.alpha,
        "fill_alpha": operator.fill_alpha,
        "width": operator.width,
    }


def line_from_grid_slice_operator(
    field: Field,
    operator: GridSliceOperatorConfig,
):
    if field.values.ndim != 2:
        raise ValueError("grid slice operators require a 2D field")
    slice_dim, idx, slice_value = resolve_grid_slice_position(
        {dim: field.coord(dim) for dim in field.dims},
        axis=operator.axis,
        position=operator.position,
        default_axis=field.dims[-1],
    )
    other_dims = [dim for dim in field.dims if dim != slice_dim]
    if len(other_dims) != 1:
        raise ValueError(
            "grid slice operators require exactly one non-sliced dimension"
        )
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
    field: Field,
    operator: GridSliceOperatorConfig,
) -> Field:
    x, y, x_dim, slice_dim, slice_value = line_from_grid_slice_operator(
        field,
        operator,
    )
    return Field(
        id=f"{field.id} at {slice_dim}={slice_value:.3f}",
        values=y,
        dims=(x_dim,),
        coords={x_dim: x},
    )


class _GridSliceAdapter:
    """Grid-slice refresh, dependency, and data-resolution behavior."""

    _VALUE_BINDING_PROPS = frozenset(
        {"axis", "position", "color", "alpha", "fill_alpha", "width"}
    )
    _COMPUTE_PROPS = frozenset({"inputs", "field", "axis", "position"})

    @staticmethod
    def _config(operator: ExtensionOperatorSpec) -> GridSliceOperatorConfig:
        return grid_slice_config(operator)

    def _slices_view(self, ctx) -> bool:
        config = self._config(ctx.op)
        view_field = getattr(ctx.view, "field_id", None)
        if view_field is None:
            return False
        return _ref(config.field_id, ctx.op_ref.fragment_id) == _ref(
            view_field,
            ctx.view_ref.fragment_id,
        )

    def on_value_change(self, ctx, value_key) -> set:
        if not self._slices_view(ctx):
            return set()
        op, frag = ctx.op, ctx.op_ref.fragment_id
        if any(
            _binding_matches(op.properties.get(prop), value_key, frag)
            for prop in self._VALUE_BINDING_PROPS
        ):
            return {RefreshTarget(OPERATOR_OVERLAY, ctx.view_id)}
        return set()

    def on_field_replace(self, ctx, field_ref) -> set:
        if getattr(ctx.view, "field_id", None) is None:
            return set()
        config = self._config(ctx.op)
        if _ref(config.field_id, ctx.op_ref.fragment_id) == field_ref:
            return {RefreshTarget(OPERATOR_OVERLAY, ctx.view_id)}
        return set()

    def on_operator_patch(self, ctx, changed_props) -> set:
        if self._slices_view(ctx):
            return {RefreshTarget(OPERATOR_OVERLAY, ctx.view_id)}
        return set()

    def affects_output(self, changed_props) -> bool:
        return bool(changed_props & self._COMPUTE_PROPS)

    def output_field_deps(self, op, fragment_id) -> tuple:
        del fragment_id
        return (self._config(op).field_id,)

    def output_binds_value(self, op, value_key, fragment_id) -> bool:
        config = self._config(op)
        return _binding_matches(
            config.axis,
            value_key,
            fragment_id,
        ) or _binding_matches(
            config.position,
            value_key,
            fragment_id,
        )

    def resolve_field(
        self,
        op,
        get_field,
        values,
        fragment_id,
    ) -> Field | None:
        config = self._config(op)
        source = get_field(config.field_id)
        if source is None:
            return None
        return field_from_grid_slice_operator(
            source,
            config.resolved(values, fragment_id),
        )


register_operator_adapter(GRID_SLICE_OPERATOR_KIND, _GridSliceAdapter())


__all__ = [
    "GRID_SLICE_OPERATOR_KIND",
    "GridSliceOperatorConfig",
    "OPERATOR_OVERLAY",
    "field_from_grid_slice_operator",
    "grid_slice_config",
    "line_from_grid_slice_operator",
    "overlay_from_grid_slice_operator",
    "resolve_grid_slice_position",
]
