from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from compneurovis.core.field import Field
from compneurovis.core.operators import OperatorSpec
from compneurovis.frontends.vispy.registries.operators import register_operator_adapter
from compneurovis.frontends.vispy.bindings import (
    _binding_matches,
    resolve_binding,
)
from compneurovis.components.surface.data import surface_scene_from_field
from compneurovis.components.grid_slice.overlay import SurfaceSliceOverlay
from compneurovis.frontends.vispy.registries.visual_contributions import (
    register_scene_contribution,
)

GRID_SLICE_OPERATOR_KIND = "grid_slice"
GRID_SLICE_OVERLAY_KIND = "grid_slice_overlay"


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
    def from_view(
        cls,
        operator: OperatorSpec,
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
    operator: OperatorSpec,
) -> GridSliceOperatorConfig:
    return GridSliceOperatorConfig.from_view(operator)


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
        attrs={
            "source_field_id": field.id,
            "slice_dim": slice_dim,
            "slice_value": slice_value,
        },
    )


class _GridSliceAdapter:
    """Grid-slice refresh, dependency, and data-resolution behavior."""

    _COMPUTE_PROPS = frozenset({"inputs", "field", "axis", "position"})

    @staticmethod
    def _config(operator: OperatorSpec) -> GridSliceOperatorConfig:
        return grid_slice_config(operator)

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
        ctx,
    ) -> Field | None:
        config = self._config(op)
        source = ctx.field(config.field_id)
        if source is None:
            return None
        return field_from_grid_slice_operator(
            source,
            config.resolved(ctx.values, ctx.fragment_id),
        )


class _GridSliceOverlayRenderer:
    """Scene layer owned entirely by the grid-slice contributor."""

    def __init__(self, context, spec):
        del spec
        self._overlay = SurfaceSliceOverlay(context.surface)

    def refresh(
        self, spec, inputs, geometries, selections, properties, values
    ) -> None:
        del spec, geometries, selections, values
        surface_field = inputs.get("surface")
        sliced_field = inputs.get("slice")
        if surface_field is None or sliced_field is None:
            self.clear()
            return
        scene_data = surface_scene_from_field(surface_field)
        slice_dim = sliced_field.attrs.get("slice_dim")
        slice_value = sliced_field.attrs.get("slice_value")
        if slice_dim is None or slice_value is None:
            self.clear()
            return
        if slice_dim == scene_data.x_dim:
            axis = "x"
        elif slice_dim == scene_data.y_dim:
            axis = "y"
        else:
            self.clear()
            return
        display_scale = tuple(
            float(item) for item in properties.get("display_scale", (1, 1, 1))
        )
        if len(display_scale) != 3 or not all(
            np.isfinite(item) and item > 0 for item in display_scale
        ):
            raise ValueError(
                "Grid-slice display_scale must contain three positive finite values"
            )
        x_scale, y_scale, z_scale = display_scale
        self._overlay.set_slice(
            axis=axis,
            value=float(slice_value) * (x_scale if axis == "x" else y_scale),
            color=properties.get("color", "#111111"),
            alpha=properties.get("alpha", 0.95),
            fill_alpha=properties.get("fill_alpha", 0.0),
            width=properties.get("width", 3.0),
            x=scene_data.x_grid * x_scale,
            y=scene_data.y_grid * y_scale,
            z=scene_data.z * z_scale,
        )

    def clear(self) -> None:
        self._overlay.clear()


_GRID_SLICE_ADAPTER = _GridSliceAdapter()


def register_grid_slice_vispy() -> None:
    """Register the first-party GridSlice operator and owned Scene3D overlay."""
    register_operator_adapter(GRID_SLICE_OPERATOR_KIND, _GRID_SLICE_ADAPTER)
    register_scene_contribution(
        GRID_SLICE_OVERLAY_KIND, _GridSliceOverlayRenderer
    )


__all__ = [
    "GRID_SLICE_OPERATOR_KIND",
    "GRID_SLICE_OVERLAY_KIND",
    "GridSliceOperatorConfig",
    "field_from_grid_slice_operator",
    "grid_slice_config",
    "line_from_grid_slice_operator",
    "register_grid_slice_vispy",
    "resolve_grid_slice_position",
]
