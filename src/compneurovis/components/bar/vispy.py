"""Vispy/PyQtGraph implementation of the Bar component."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pyqtgraph as pg

from compneurovis.core._immutability import FrozenDict
from compneurovis.core.field import Field
from compneurovis.core.views import ExtensionViewSpec, ValueOrBinding, ViewSpec
from compneurovis.frontends.vispy.bindings import resolve_binding
from compneurovis.frontends.vispy.plot2d.host import Plot2DHostPanel
from compneurovis.frontends.vispy.plot2d.styles import (
    freeze_series_style as _freeze_series_style,
    series_style as _series_style,
)

SeriesStyle = Any

@dataclass(frozen=True, slots=True)
class BarPlotViewSpec(ViewSpec):
    """Live bar chart render-config (one bar per ``category_dim`` coord label).

    Frontend render-config, not an authored view: built by ``BarPlotHost`` from an
    ``ExtensionViewSpec(kind="bar_plot")``. No ``panel_kind``/``kind``.
    """

    field_id: str = ""
    category_dim: str | None = None
    x_label: str = ""
    y_label: str = "y"
    y_unit: str = ""
    color: ValueOrBinding = "#1f77b4"
    colors: SeriesStyle = field(default_factory=FrozenDict)
    background_color: ValueOrBinding = "w"
    show_legend: bool = False
    y_min: float | None = None
    y_max: float | None = None
    max_refresh_hz: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "colors", _freeze_series_style(self.colors))

class BarPlotCanvas(pg.PlotWidget):
    """Bar-specific Plot2D canvas with no dependency on line rendering."""

    def __init__(
        self,
        parent=None,
        *,
        show_internal_title: bool = True,
        perf_panel_id: str | None = None,
        perf_view_id: str | None = None,
    ):
        super().__init__(parent=parent, title="Plot" if show_internal_title else "")
        self._show_internal_title = show_internal_title
        self._resolved_title = ""
        self._bar_item: pg.BarGraphItem | None = None
        self._tick_signature: tuple[str, ...] | None = None
        self._brush_signature: tuple[Any, ...] | None = None
        self._x_range: tuple[float, float] | None = None
        self._y_applied: tuple[float | None, float | None] | bool | None = None
        self._background: Any = None
        self.setBackground("w")

    @property
    def resolved_title(self) -> str:
        return self._resolved_title

    def _set_resolved_title(self, title: str) -> None:
        self._resolved_title = str(title)
        self.setTitle(self._resolved_title if self._show_internal_title else "")

    def refresh(
        self,
        view: BarPlotViewSpec | None,
        field: Field | None,
        values: dict[str, Any],
    ) -> None:
        if view is None or field is None:
            if self._bar_item is not None:
                self._bar_item.setOpts(height=np.zeros(0))
            self._set_resolved_title("")
            return
        background = resolve_binding(view.background_color, values)
        if background is not None and background != self._background:
            self.setBackground(background)
            self._background = background
        category_dim = (
            view.category_dim
            if view.category_dim in field.dims
            else (field.dims[0] if field.dims else None)
        )
        heights = np.asarray(field.values, dtype=np.float64).reshape(-1)
        labels = (
            [str(label) for label in field.coord(category_dim)]
            if category_dim is not None
            else [str(index) for index in range(len(heights))]
        )
        brushes = tuple(
            resolve_binding(
                _series_style(view.colors, label, index, view.color), values
            )
            for index, label in enumerate(labels)
        )
        structural = tuple(labels)
        if self._bar_item is None or structural != self._tick_signature:
            x = np.arange(len(heights), dtype=np.float64)
            if self._bar_item is None:
                self._bar_item = pg.BarGraphItem(
                    x=x, height=heights, width=0.8, brushes=list(brushes)
                )
                self.addItem(self._bar_item)
            else:
                self._bar_item.setOpts(
                    x=x, height=heights, width=0.8, brushes=list(brushes)
                )
            self.getAxis("bottom").setTicks(
                [[(index, label) for index, label in enumerate(labels)]]
            )
            self.setLabel("bottom", view.x_label)
            self.setLabel("left", view.y_label, view.y_unit)
            self._tick_signature = structural
            self._brush_signature = brushes
            view_box = self.plotItem.getViewBox()
            x_range = (-0.6, max(0.4, len(heights) - 0.4))
            if x_range != self._x_range:
                view_box.setXRange(*x_range, padding=0)
                self._x_range = x_range
            y_target = (view.y_min, view.y_max)
            if view.y_min is not None and view.y_max is not None:
                if y_target != self._y_applied:
                    view_box.setYRange(
                        float(view.y_min), float(view.y_max), padding=0
                    )
                    self._y_applied = y_target
            elif self._y_applied is not False:
                view_box.enableAutoRange(y=True)
                self._y_applied = False
        elif brushes != self._brush_signature:
            self._bar_item.setOpts(height=heights, brushes=list(brushes))
            self._brush_signature = brushes
        else:
            self._bar_item.setOpts(height=heights)
        self._set_resolved_title(str(resolve_binding(view.title, values) or ""))


class BarPlotHost(Plot2DHostPanel):
    """Extension host: adapts ``ExtensionViewSpec(kind="bar_plot")`` onto the shared
    line/bar visual. A sibling of :class:`LinePlotHost` -- reconstructs the
    ``BarPlotViewSpec`` from the view's raw ``properties`` and hands the real
    ``values`` to the visual (which renders bars via ``_refresh_bars``).
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(canvas_factory=BarPlotCanvas, **kwargs)

    def refresh(
        self,
        view: ExtensionViewSpec,
        inputs: Mapping[str, Any],
        properties: Mapping[str, Any],
        values: Mapping[str, Any] | None = None,
    ) -> None:
        props = dict(view.properties)
        props.pop("max_refresh_hz", None)  # carried at the ExtensionViewSpec level
        bar_view = BarPlotViewSpec(
            id=view.id,
            title=view.title,
            field_id=view.inputs.get("data", ""),
            max_refresh_hz=view.max_refresh_hz,
            **props,
        )
        self._render(bar_view, inputs.get("data"), dict(values or {}))

__all__ = ["BarPlotHost", "BarPlotViewSpec"]
