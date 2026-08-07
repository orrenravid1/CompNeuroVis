"""Package-owned interpretation of the neutral point-cloud slice operator."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

import numpy as np

import compneurovis as cnv

from cnv_pointcloud_demo.authoring import GEOMETRY_KIND


SLICE_OPERATOR_KIND = "point_cloud_plane_slice"
SLICE_OVERLAY_KIND = "point_cloud_plane_slice_overlay"
SLICE_FIELD_SCHEMA = "point_cloud_plane_slice/v1"
_AXES = ("x", "y", "z")


def _resolve_binding(value: Any, values: Mapping[Any, Any], fragment_id: str) -> Any:
    if isinstance(value, cnv.ValueBindingSpec):
        scoped = cnv.AppRef(value.key, fragment_id=fragment_id)
        return values.get(scoped, values.get(value.key))
    if isinstance(value, cnv.AppRef):
        return values.get(value, values.get(value.id, value))
    return value


def _contains_binding(
    value: Any,
    value_key: str | cnv.AppRef,
    fragment_id: str,
) -> bool:
    if isinstance(value, cnv.ValueBindingSpec):
        binding_ref = cnv.AppRef(value.key, fragment_id=fragment_id)
        return value_key == value.key or cnv.app_ref(value_key) == binding_ref
    if isinstance(value, cnv.AppRef):
        return cnv.app_ref(value_key) == cnv.app_ref(
            value,
            fragment_id=fragment_id,
        )
    if isinstance(value, Mapping):
        return any(
            _contains_binding(item, value_key, fragment_id) for item in value.values()
        )
    if isinstance(value, (tuple, list)):
        return any(_contains_binding(item, value_key, fragment_id) for item in value)
    return False


@dataclass(frozen=True, slots=True)
class PointCloudSliceConfig:
    """Typed package-local view of a neutral operator spec."""

    id: str
    geometry_id: str | cnv.AppRef
    values_id: str | cnv.AppRef
    axis: Any = "z"
    position: Any = 0.5
    thickness: Any = 0.15
    color: Any = "#ffb000"
    alpha: Any = 0.18

    @classmethod
    def from_view(
        cls,
        operator: cnv.OperatorSpec,
    ) -> "PointCloudSliceConfig":
        if operator.kind != SLICE_OPERATOR_KIND:
            raise ValueError(f"Expected {SLICE_OPERATOR_KIND!r}, got {operator.kind!r}")
        properties = operator.properties
        return cls(
            id=operator.id,
            geometry_id=operator.geometries.get("points", ""),
            values_id=operator.inputs.get("values", ""),
            axis=properties.get("axis", "z"),
            position=properties.get("position", 0.5),
            thickness=properties.get("thickness", 0.15),
            color=properties.get("color", "#ffb000"),
            alpha=properties.get("alpha", 0.18),
        )

    def resolved(
        self,
        values: Mapping[Any, Any],
        fragment_id: str,
    ) -> "PointCloudSliceConfig":
        return replace(
            self,
            axis=_resolve_binding(self.axis, values, fragment_id),
            position=_resolve_binding(self.position, values, fragment_id),
            thickness=_resolve_binding(self.thickness, values, fragment_id),
            color=_resolve_binding(self.color, values, fragment_id),
            alpha=_resolve_binding(self.alpha, values, fragment_id),
        )


@dataclass(frozen=True, slots=True)
class PointCloudSlice:
    """Resolved slab and projected samples used by both output and overlay."""

    axis: str
    axis_index: int
    projected_axes: tuple[str, str]
    center: float
    half_width: float
    bounds_min: np.ndarray
    bounds_max: np.ndarray
    entity_ids: np.ndarray
    projected: np.ndarray
    values: np.ndarray


def point_cloud_slice(
    geometry: cnv.GeometrySpec,
    values_field: cnv.Field,
    config: PointCloudSliceConfig,
) -> PointCloudSlice:
    """Select a normalized finite slab and project its points into the plane."""

    if geometry.kind != GEOMETRY_KIND:
        raise ValueError(f"Point-cloud slice requires {GEOMETRY_KIND!r} geometry")
    positions = np.asarray(geometry.data["positions"], dtype=np.float32)
    if positions.ndim != 2 or positions.shape[1] != 3:
        raise ValueError("Point-cloud positions must have shape (n, 3)")
    entity_ids = np.asarray(geometry.data["entity_ids"]).astype(str)
    if len(entity_ids) != len(positions):
        raise ValueError("Point-cloud entity ids must match the point count")
    scalars = np.asarray(values_field.values, dtype=np.float32).reshape(-1)
    if len(scalars) != len(positions):
        raise ValueError("Point-cloud scalar values must match the point count")

    axis = str(config.axis).strip().lower()
    if axis not in _AXES:
        raise ValueError("Point-cloud slice axis must be one of 'x', 'y', or 'z'")
    axis_index = _AXES.index(axis)
    bounds_min = np.min(positions, axis=0) if len(positions) else np.zeros(3)
    bounds_max = np.max(positions, axis=0) if len(positions) else np.zeros(3)
    span = float(bounds_max[axis_index] - bounds_min[axis_index])
    position = float(np.clip(float(config.position), 0.0, 1.0))
    thickness = float(np.clip(float(config.thickness), 0.0, 1.0))
    center = float(bounds_min[axis_index] + position * span)
    half_width = 0.5 * thickness * span
    tolerance = max(abs(span) * 1e-7, np.finfo(np.float32).eps)
    mask = np.abs(positions[:, axis_index] - center) <= half_width + tolerance
    projected_indices = tuple(index for index in range(3) if index != axis_index)
    projected_axes = tuple(_AXES[index] for index in projected_indices)
    return PointCloudSlice(
        axis=axis,
        axis_index=axis_index,
        projected_axes=(projected_axes[0], projected_axes[1]),
        center=center,
        half_width=half_width,
        bounds_min=np.asarray(bounds_min, dtype=np.float32),
        bounds_max=np.asarray(bounds_max, dtype=np.float32),
        entity_ids=entity_ids[mask],
        projected=positions[mask][:, projected_indices],
        values=scalars[mask],
    )


def field_from_point_cloud_slice(
    geometry: cnv.GeometrySpec,
    values_field: cnv.Field,
    config: PointCloudSliceConfig,
) -> cnv.Field:
    """Encode projected x/y/scalar columns in an ordinary, explicit Field."""

    sliced = point_cloud_slice(geometry, values_field, config)
    columns = np.column_stack((sliced.projected, sliced.values)).astype(
        np.float32,
        copy=False,
    )
    return cnv.Field(
        id=config.id,
        values=columns,
        dims=("point", "component"),
        coords={
            "point": sliced.entity_ids,
            "component": np.asarray(("u", "v", "value")),
        },
        unit=values_field.unit,
        attrs={
            "schema": SLICE_FIELD_SCHEMA,
            "slice_axis": sliced.axis,
            "slice_center": sliced.center,
            "slice_half_width": sliced.half_width,
            "u_axis": sliced.projected_axes[0],
            "v_axis": sliced.projected_axes[1],
        },
    )


__all__ = [
    "PointCloudSlice",
    "PointCloudSliceConfig",
    "SLICE_FIELD_SCHEMA",
    "SLICE_OPERATOR_KIND",
    "SLICE_OVERLAY_KIND",
    "_contains_binding",
    "field_from_point_cloud_slice",
    "point_cloud_slice",
]
