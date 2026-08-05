"""Surface widget lowering.

Data production lives in a ``SnapshotProducer`` (``data_producers``) — a surface
is just the 2-D case of the general N-dimensional snapshot field. This module
keeps only the presentation binding and the authored ``Surface`` widget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from compneurovis.core.app_spec import PANEL_KIND_VIEW_3D, PanelSpec
from compneurovis.core.geometry import GridGeometrySpec
from compneurovis.core.views import ExtensionViewSpec
from compneurovis.inline._ids import slug
from compneurovis.inline.compiler import WidgetContribution
from compneurovis.inline.data_producers import SnapshotProducer
from compneurovis.inline.widgets.api import Widget
from compneurovis.inline.refs import SurfaceRef, bind


@dataclass
class SurfaceBinding:
    """Lower a grid field into a 3-D surface panel (view + geometry + panel).

    Holds a reference to the field's producer for the static field declaration;
    it does no data production itself.
    """

    name: str
    dims: tuple[str, str]
    coords: dict[str, Any]
    camera_distance: float | None = 30.0
    camera_elevation: float = 30.0
    camera_azimuth: float = 30.0
    view_kwargs: dict[str, Any] = field(default_factory=dict)
    _field_id: str = field(init=False, default="")
    _geometry_id: str = field(init=False, default="")
    _view_id: str = field(init=False, default="")
    _panel_id: str = field(init=False, default="")
    _operator_ids: list[str] = field(init=False, default_factory=list)
    _producer: SnapshotProducer | None = field(init=False, default=None)

    def _register(self, index: int) -> None:
        name_slug = slug(self.name)
        self._field_id = f"surface_{index}_{name_slug}_field"
        self._geometry_id = f"surface_{index}_{name_slug}_grid"
        self._view_id = f"surface_{index}_{name_slug}"
        self._panel_id = f"surface-panel-{index}-{name_slug}"

    def _geometry_spec(self) -> GridGeometrySpec:
        return GridGeometrySpec(
            id=self._geometry_id,
            dims=self.dims,
            coords={dim: np.asarray(self.coords[dim]) for dim in self.dims},
        )

    def _view_spec(self) -> ExtensionViewSpec:
        # A surface is a first-class extension view (kind="surface") in a VIEW_3D
        # panel; the frontend reconstructs its typed render-config at the boundary.
        kwargs = {key: bind(value) for key, value in self.view_kwargs.items()}
        title = kwargs.pop("title", self.name)
        max_refresh_hz = kwargs.pop("max_refresh_hz", None)
        return ExtensionViewSpec(
            id=self._view_id,
            title=title,
            kind="surface",
            inputs={"field": self._field_id},
            properties={
                "geometry_id": self._geometry_id,
                # Camera is a 3-D *view* property, not a generic panel field.
                "camera_distance": self.camera_distance,
                "camera_elevation": self.camera_elevation,
                "camera_azimuth": self.camera_azimuth,
                **kwargs,
            },
            max_refresh_hz=max_refresh_hz,
            panel_kind=PANEL_KIND_VIEW_3D,
        )

    def _panel_spec(self) -> PanelSpec:
        return PanelSpec(
            id=self._panel_id,
            kind=PANEL_KIND_VIEW_3D,
            view_ids=(self._view_id,),
            operator_ids=tuple(self._operator_ids),
        )

    def contribution(self, backend: Any = None) -> WidgetContribution:
        del backend
        return WidgetContribution(
            fields=(self._producer.field_spec(),),
            geometries=(self._geometry_spec(),),
            views=(self._view_spec(),),
            panel=self._panel_spec(),
        )


@dataclass(frozen=True, slots=True)
class Surface(Widget[SurfaceRef]):
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

    def declare(self, context) -> SurfaceRef:
        if self.values is None and self.read is None:
            raise ValueError("surface requires values=... or read=...")
        dims, coords = self._resolve_grid()

        binding = SurfaceBinding(
            name=self.name,
            dims=dims,
            coords=coords,
            camera_distance=self.camera_distance,
            camera_elevation=self.camera_elevation,
            camera_azimuth=self.camera_azimuth,
            view_kwargs=dict(self.style),
        )
        context._register_surface(binding)
        binding._producer = context._declare_grid_field(
            field_id=binding._field_id,
            dims=dims,
            coords=coords,
            values=self.values,
            read=self.read,
            unit=self.unit,
            replace_includes_coords=True,
        )
        return SurfaceRef(binding)

    def _resolve_grid(self) -> tuple[tuple[str, str], dict[str, np.ndarray]]:
        raw = self.read() if self.read is not None else self.values
        values = np.asarray(raw, dtype=np.float32)
        if values.ndim != 2:
            raise ValueError(f"surface({self.name!r}) values must be 2-D")
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
            raise ValueError(f"surface({self.name!r}) x/y coords must be one-dimensional")
        if len(x) != x_count or len(y) != y_count:
            raise ValueError(
                f"surface({self.name!r}) coord lengths must match values shape; "
                f"got len(x)={len(x)}, len(y)={len(y)}, shape={values.shape}"
            )
        return (self.y_dim, self.x_dim), {self.y_dim: y, self.x_dim: x}


__all__ = ["Surface", "SurfaceBinding"]
