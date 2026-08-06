"""Grid-slice widget declaration and AppSpec lowering.

A grid slice is a *surface operation*: it draws the cross-section overlay on the
surface and produces the sliced profile as a plain ``DataRef``. It does not make
a plot -- the sliced profile is ordinary data, so compose a consumer such as
``source.line(source=slice)`` (or anything that reads a ``DataRef``) to view it.
Nothing about the produced data is line-plot-specific.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from compneurovis.inline.refs import (
    DataRef,
    SurfaceRef,
)
from compneurovis.inline.widgets.api import Widget


@dataclass(frozen=True, slots=True)
class GridSlice(Widget[DataRef]):
    """Reusable surface cross-section accepted by ``source.add()``.

    Draws the slice overlay on the surface and returns the sliced profile as a
    ``DataRef``; compose ``source.line(source=...)`` (or any data consumer) to
    plot it.
    """

    name: str
    surface: SurfaceRef
    axis: Any
    position: Any
    overlay: dict[str, Any] | None = None

    def declare(self, context) -> DataRef:
        surface_data = DataRef(_field_id=self.surface.field_id)
        sliced = context.operator(
            "grid_slice",
            self.name,
            inputs={"field": surface_data},
            properties={
                "axis": self.axis,
                "position": self.position,
            },
        )
        context.visual_contribution(
            "grid_slice_overlay",
            f"{self.name} overlay",
            target=self.surface,
            capability="scene3d.layers/v1",
            inputs={"surface": surface_data, "slice": sliced},
            properties={} if self.overlay is None else dict(self.overlay),
        )
        return sliced


__all__ = ["GridSlice"]
