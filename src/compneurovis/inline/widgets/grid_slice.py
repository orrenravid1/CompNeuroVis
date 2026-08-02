"""Grid-slice widget declaration and AppSpec lowering."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from compneurovis.core.operators import GridSliceOperatorSpec
from compneurovis.inline._ids import slug
from compneurovis.inline.compiler import WidgetContribution
from compneurovis.inline.refs import (
    GridSliceRef,
    SurfaceRef,
    bind,
    binding_key,
)
from compneurovis.inline.widgets.line import LineBinding
from compneurovis.inline.widgets.api import Widget
from compneurovis.inline.widgets.surface import SurfaceBinding


@dataclass
class GridSliceBinding:
    """Operator and line presentation for one surface cross-section."""

    name: str
    surface: SurfaceBinding
    axis: Any
    position: Any
    line_kwargs: dict[str, Any] = field(default_factory=dict)
    overlay_kwargs: dict[str, Any] = field(default_factory=dict)
    _operator_id: str = field(init=False, default="")
    _view_id: str = field(init=False, default="")
    _panel_id: str = field(init=False, default="")

    def _register(self, index: int) -> None:
        name_slug = slug(self.name)
        self._operator_id = f"grid_slice_{index}_{name_slug}"
        self._view_id = f"grid_slice_{index}_{name_slug}_plot"
        self._panel_id = f"grid-slice-panel-{index}-{name_slug}"
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

    def _line_binding(self) -> LineBinding:
        kwargs = {key: bind(value) for key, value in self.line_kwargs.items()}
        return LineBinding(
            operator_id=self._operator_id,
            view_id=self._view_id,
            panel_id=self._panel_id,
            title=kwargs.pop("title", self.name),
            x_dim=kwargs.pop("x_dim", None),
            levels=kwargs.pop("levels", ()),
            style=kwargs,
        )

    def contribution(self, backend: Any = None) -> WidgetContribution:
        del backend
        line = self._line_binding()
        return WidgetContribution(
            operators=(self._operator_spec(),),
            views=(line.view_spec(),),
            panel=line.panel_spec(),
        )


@dataclass(frozen=True, slots=True)
class GridSlice(Widget[GridSliceRef]):
    """Reusable surface cross-section widget accepted by ``source.add()``."""

    name: str
    surface: SurfaceRef
    axis: Any
    position: Any
    overlay: dict[str, Any] | None = None
    style: dict[str, Any] = field(default_factory=dict)

    def declare(self, context) -> GridSliceRef:
        binding = GridSliceBinding(
            name=self.name,
            surface=self.surface._binding,
            axis=self.axis,
            position=self.position,
            line_kwargs=dict(self.style),
            overlay_kwargs={} if self.overlay is None else dict(self.overlay),
        )
        context._register_grid_slice(binding)
        return GridSliceRef(binding)


__all__ = ["GridSlice", "GridSliceBinding"]
