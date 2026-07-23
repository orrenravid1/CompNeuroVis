"""Surface widget data production and AppSpec lowering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from compneurovis.core.app_spec import PANEL_KIND_VIEW_3D, PanelSpec
from compneurovis.core.field import FieldSpec
from compneurovis.core.geometry import GridGeometrySpec
from compneurovis.core.messages import FieldReplace, update_message
from compneurovis.core.views import SurfaceViewSpec
from compneurovis.inline._ids import slug
from compneurovis.inline.compiler import WidgetContribution
from compneurovis.inline.handles import SurfaceHandle, bind


@dataclass
class SurfaceBinding:
    """Two-dimensional static or callable-backed surface widget."""

    name: str
    values: Any
    x: Any | None = None
    y: Any | None = None
    read: Callable[[], Any] | None = None
    x_dim: str = "x"
    y_dim: str = "y"
    unit: str | None = None
    camera_distance: float | None = 30.0
    camera_elevation: float = 30.0
    camera_azimuth: float = 30.0
    view_kwargs: dict[str, Any] = field(default_factory=dict)
    _field_id: str = field(init=False, default="")
    _geometry_id: str = field(init=False, default="")
    _view_id: str = field(init=False, default="")
    _panel_id: str = field(init=False, default="")
    _operator_ids: list[str] = field(init=False, default_factory=list)

    def _register(self, index: int) -> None:
        name_slug = slug(self.name)
        self._field_id = f"surface_{index}_{name_slug}_field"
        self._geometry_id = f"surface_{index}_{name_slug}_grid"
        self._view_id = f"surface_{index}_{name_slug}"
        self._panel_id = f"surface-panel-{index}-{name_slug}"

    def _values(self) -> np.ndarray:
        raw = self.read() if self.read is not None else self.values
        values = np.asarray(raw, dtype=np.float32)
        if values.ndim != 2:
            raise ValueError(f"surface({self.name!r}) values must be 2-D")
        return values

    def _coords(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        y_count, x_count = values.shape
        x = (
            np.arange(x_count, dtype=np.float32)
            if self.x is None
            else np.asarray(self.x, dtype=np.float32)
        )
        y = (
            np.arange(y_count, dtype=np.float32)
            if self.y is None
            else np.asarray(self.y, dtype=np.float32)
        )
        if x.ndim != 1 or y.ndim != 1:
            raise ValueError(
                f"surface({self.name!r}) x/y coords must be one-dimensional"
            )
        if len(x) != x_count or len(y) != y_count:
            raise ValueError(
                f"surface({self.name!r}) coord lengths must match values shape; "
                f"got len(x)={len(x)}, len(y)={len(y)}, shape={values.shape}"
            )
        return x, y

    def _field_spec(self) -> FieldSpec:
        values = self._values()
        x, y = self._coords(values)
        return FieldSpec(
            id=self._field_id,
            initial_values=values,
            dims=(self.y_dim, self.x_dim),
            coords={self.y_dim: y, self.x_dim: x},
            unit=self.unit,
        )

    def _geometry_spec(self) -> GridGeometrySpec:
        values = self._values()
        x, y = self._coords(values)
        return GridGeometrySpec(
            id=self._geometry_id,
            dims=(self.y_dim, self.x_dim),
            coords={self.y_dim: y, self.x_dim: x},
        )

    def _view_spec(self) -> SurfaceViewSpec:
        kwargs = {key: bind(value) for key, value in self.view_kwargs.items()}
        title = kwargs.pop("title", self.name)
        return SurfaceViewSpec(
            id=self._view_id,
            title=title,
            field_id=self._field_id,
            geometry_id=self._geometry_id,
            **kwargs,
        )

    def _panel_spec(self) -> PanelSpec:
        return PanelSpec(
            id=self._panel_id,
            kind=PANEL_KIND_VIEW_3D,
            view_ids=(self._view_id,),
            operator_ids=tuple(self._operator_ids),
            camera_distance=self.camera_distance,
            camera_elevation=self.camera_elevation,
            camera_azimuth=self.camera_azimuth,
        )

    def contribution(self, backend: Any = None) -> WidgetContribution:
        del backend
        return WidgetContribution(
            fields=(self._field_spec(),),
            geometries=(self._geometry_spec(),),
            views=(self._view_spec(),),
            panel=self._panel_spec(),
        )

    def _replace_message(self):
        values = self._values()
        x, y = self._coords(values)
        return update_message(
            FieldReplace(
                field_id=self._field_id,
                values=values,
                coords={self.y_dim: y, self.x_dim: x},
            )
        )


@dataclass(frozen=True, slots=True)
class Surface:
    """Reusable surface widget accepted by ``source.add()``."""

    name: str
    values: Any = None
    read: Callable[[], Any] | None = None
    x: Any | None = None
    y: Any | None = None
    x_dim: str = "x"
    y_dim: str = "y"
    unit: str | None = None
    camera_distance: float | None = 30.0
    camera_elevation: float = 30.0
    camera_azimuth: float = 30.0
    style: dict[str, Any] = field(default_factory=dict)

    def attach(self, context) -> SurfaceHandle:
        if self.values is None and self.read is None:
            raise ValueError("surface requires values=... or read=...")
        binding = SurfaceBinding(
            name=self.name,
            values=self.values,
            read=self.read,
            x=self.x,
            y=self.y,
            x_dim=self.x_dim,
            y_dim=self.y_dim,
            unit=self.unit,
            camera_distance=self.camera_distance,
            camera_elevation=self.camera_elevation,
            camera_azimuth=self.camera_azimuth,
            view_kwargs=dict(self.style),
        )
        context._register_surface(binding)
        return SurfaceHandle(binding)


__all__ = ["Surface", "SurfaceBinding"]
