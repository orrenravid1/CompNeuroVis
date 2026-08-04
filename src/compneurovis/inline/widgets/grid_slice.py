"""Grid-slice widget declaration and AppSpec lowering.

A grid slice is a *surface operation*: it draws the cross-section overlay on the
surface and produces the sliced profile as a plain ``DataRef``. It does not make
a plot -- the sliced profile is ordinary data, so compose a consumer such as
``source.line(source=slice)`` (or anything that reads a ``DataRef``) to view it.
Nothing about the produced data is line-plot-specific.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from compneurovis.core.operators import GridSliceOperatorSpec
from compneurovis.inline._ids import slug
from compneurovis.inline.compiler import WidgetContribution
from compneurovis.inline.refs import (
    DataRef,
    SurfaceRef,
    bind,
    binding_key,
)
from compneurovis.inline.widgets.api import Widget
from compneurovis.inline.widgets.surface import SurfaceBinding


@dataclass
class GridSliceBinding:
    """Cross-section operator over a surface: the overlay + the sliced data source."""

    name: str
    surface: SurfaceBinding
    axis: Any
    position: Any
    overlay_kwargs: dict[str, Any] = field(default_factory=dict)
    _operator_id: str = field(init=False, default="")

    def _register(self, index: int) -> None:
        self._operator_id = f"grid_slice_{index}_{slug(self.name)}"
        self.surface._operator_ids.append(self._operator_id)

    def _operator_spec(self) -> GridSliceOperatorSpec:
        return GridSliceOperatorSpec(
            id=self._operator_id,
            field_id=self.surface._field_id,
            geometry_id=self.surface._geometry_id,
            axis_value_key=binding_key(self.axis),
            position_value_key=binding_key(self.position),
            **{key: bind(value) for key, value in self.overlay_kwargs.items()},
        )

    def data_ref(self) -> DataRef:
        # The slice output is plain data. A consumer reads it as
        # ``inputs["data"] = operator id``, which the frontend resolves to the
        # computed 1-D field -- the same path any stored field takes.
        return DataRef(_field_id=self._operator_id)

    def contribution(self, backend: Any = None) -> WidgetContribution:
        del backend
        return WidgetContribution(operators=(self._operator_spec(),))


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
        binding = GridSliceBinding(
            name=self.name,
            surface=self.surface._binding,
            axis=self.axis,
            position=self.position,
            overlay_kwargs={} if self.overlay is None else dict(self.overlay),
        )
        context._register_grid_slice(binding)
        return binding.data_ref()


__all__ = ["GridSlice", "GridSliceBinding"]
