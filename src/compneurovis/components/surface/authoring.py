"""Surface widget lowering.

Data production lives in a ``SnapshotProducer`` (``data_producers``) — a surface
is just the 2-D case of the general N-dimensional snapshot field. This module
keeps only the presentation binding and the authored ``Surface`` widget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from compneurovis.inline.widgets.api import Widget
from compneurovis.inline.refs import SurfaceRef


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
    camera_orbit_sensitivity: float = 0.75
    camera_pan_sensitivity: float = 0.5
    camera_zoom_sensitivity: float = 0.7
    display_scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    style: dict[str, Any] = field(default_factory=dict)

    def declare(self, context) -> SurfaceRef:
        if self.values is None and self.read is None:
            raise ValueError("surface requires values=... or read=...")
        data = context.grid(
            self.name,
            values=self.values,
            read=self.read,
            x=self.x,
            y=self.y,
            x_dim=self.x_dim,
            y_dim=self.y_dim,
            unit=self.unit,
        )
        style = dict(self.style)
        title = style.pop("title", self.name)
        max_refresh_hz = style.pop("max_refresh_hz", None)
        panel = context.view(
            "surface",
            self.name,
            inputs={"field": data},
            properties={
                "camera_distance": self.camera_distance,
                "camera_elevation": self.camera_elevation,
                "camera_azimuth": self.camera_azimuth,
                "camera_orbit_sensitivity": self.camera_orbit_sensitivity,
                "camera_pan_sensitivity": self.camera_pan_sensitivity,
                "camera_zoom_sensitivity": self.camera_zoom_sensitivity,
                "display_scale": self.display_scale,
                **style,
            },
            title=title,
            panel_kind="scene_3d",
            max_refresh_hz=max_refresh_hz,
        )
        return SurfaceRef(panel.id, data._field_id)


__all__ = ["Surface"]
