"""Line widget declaration, sampling, and AppSpec lowering."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Callable, TypeAlias, TYPE_CHECKING

import numpy as np

from compneurovis.core.app_spec import PANEL_KIND_LINE_PLOT, PanelSpec
from compneurovis.core.field import FieldSpec
from compneurovis.core.messages import FieldAppend, FieldReplace, update_message
from compneurovis.core.views import LinePlotViewSpec
from compneurovis.inline._ids import slug
from compneurovis.inline.compiler import FieldInput, WidgetContribution
from compneurovis.inline.handles import DataHandle, LineHandle, bind
from compneurovis.inline.widgets.plotting import level_items, level_marker

if TYPE_CHECKING:
    from compneurovis.inline.widgets.api import WidgetAuthoringContext


SeriesReaders: TypeAlias = Callable[[], float] | Mapping[str, Callable[[], float]]


@dataclass
class LinePlotBinding:
    """Lower an already-declared data handle or operator into a line panel."""

    view_id: str
    panel_id: str
    title: Any
    field_id: str | None = None
    operator_id: str | None = None
    x_dim: str | None = "time"
    series_dim: str | None = None
    selectors: Mapping[str, Any] = field(default_factory=dict)
    levels: Sequence[Any] = ()
    field_builders: tuple[FieldInput, ...] = ()
    panel_title: str | None = None
    style: Mapping[str, Any] = field(default_factory=dict)

    def contribution(self, backend: Any = None) -> WidgetContribution:
        return WidgetContribution(
            fields=tuple(
                item(backend) if callable(item) else item
                for item in self.field_builders
            ),
            views=(self.view_spec(),),
            panel=self.panel_spec(),
        )

    def view_spec(self) -> LinePlotViewSpec:
        kwargs = {key: bind(value) for key, value in self.style.items()}
        style_levels = kwargs.pop("levels", ())
        levels = tuple(
            level_marker(item, "horizontal")
            for item in (*level_items(self.levels), *level_items(style_levels))
        )
        return LinePlotViewSpec(
            id=self.view_id,
            title=bind(self.title),
            field_id=self.field_id or "",
            operator_id=self.operator_id,
            x_dim=self.x_dim,
            series_dim=self.series_dim,
            selectors={
                dimension: bind(value) for dimension, value in self.selectors.items()
            },
            levels=levels,
            **kwargs,
        )

    def panel_spec(self) -> PanelSpec:
        return PanelSpec(
            id=self.panel_id,
            kind=PANEL_KIND_LINE_PLOT,
            view_ids=(self.view_id,),
            title=self.panel_title,
        )


@dataclass
class TraceBinding:
    """Callable-backed line data sampled into an append-only field."""

    name: str
    read: SeriesReaders
    x: Callable[[], float] | None = None
    title: str | None = None
    rolling_window: float = 500.0
    trim_to_rolling_window: bool = True
    y_min: float | None = None
    y_max: float | None = None
    y_unit: str = "a.u."
    x_unit: str = "ms"
    x_label: str = "Time"
    y_label: str = "Value"
    color: Any = "k"
    background_color: Any = "w"
    show_legend: bool | None = None
    colors: Any = field(default_factory=dict)
    linestyle: Any = "-"
    linestyles: Any = field(default_factory=dict)
    linewidth: Any = 2.0
    linewidths: Any = field(default_factory=dict)
    max_refresh_hz: float | None = None
    x_major_tick_spacing: float | None = None
    x_minor_tick_spacing: float | None = None
    levels: Sequence[Any] = ()
    max_samples: int = 2400
    _field_id: str = field(init=False, default="")
    _view_id: str = field(init=False, default="")
    _panel_id: str = field(init=False, default="")
    _buf_x: list = field(init=False, default_factory=list)
    _buf_vals: list = field(init=False, default_factory=list)
    _sampled_this_frame: bool = field(init=False, default=False)

    def _register(self, index: int) -> None:
        name_slug = slug(self.name)
        self._field_id = f"field_{index}_{name_slug}"
        self._view_id = f"view_{index}_{name_slug}"
        self._panel_id = f"panel_{index}_{name_slug}"

    def _series(self) -> dict[str, Callable[[], float]]:
        if callable(self.read):
            return {self.name: self.read}
        return dict(self.read)

    def _begin_frame(self) -> None:
        self._sampled_this_frame = False

    def _sample(self) -> None:
        series = self._series()
        self._buf_x.append(self._x_value())
        self._buf_vals.append([reader() for reader in series.values()])
        self._sampled_this_frame = True

    def _x_value(self) -> float:
        if self.x is not None:
            return float(self.x())
        return float(len(self._buf_x))

    def _drain_message(self):
        if not self._buf_x:
            return None
        x_values = self._buf_x[:]
        samples = self._buf_vals[:]
        self._buf_x.clear()
        self._buf_vals.clear()
        values = (
            np.array(samples, dtype=np.float32)
            .reshape(
                len(x_values),
                len(self._series()),
            )
            .T
        )
        return update_message(
            FieldAppend(
                field_id=self._field_id,
                append_dim="time",
                values=values,
                coord_values=np.array(x_values, dtype=np.float32),
                max_length=self.max_samples,
            )
        )

    def _field_spec(self) -> FieldSpec:
        series = self._series()
        return FieldSpec(
            id=self._field_id,
            initial_values=np.array(
                [[reader()] for reader in series.values()],
                dtype=np.float32,
            ),
            dims=("series", "time"),
            coords={
                "series": np.array(list(series.keys())),
                "time": np.array([self._x_value()], dtype=np.float32),
            },
            unit=self.y_unit,
        )

    def contribution(self, backend: Any = None) -> WidgetContribution:
        del backend
        widget = self._line_binding()
        return WidgetContribution(
            fields=(self._field_spec(),),
            views=(widget.view_spec(),),
            panel=widget.panel_spec(),
        )

    def _line_binding(self) -> LinePlotBinding:
        series = self._series()
        return LinePlotBinding(
            field_id=self._field_id,
            view_id=self._view_id,
            panel_id=self._panel_id,
            title=self.title or self.name,
            x_dim="time",
            series_dim="series",
            levels=self.levels,
            style={
                "x_label": self.x_label,
                "y_label": self.y_label,
                "x_unit": self.x_unit,
                "y_unit": self.y_unit,
                "rolling_window": self.rolling_window,
                "trim_to_rolling_window": self.trim_to_rolling_window,
                "y_min": self.y_min,
                "y_max": self.y_max,
                "color": self.color,
                "background_color": self.background_color,
                "show_legend": len(series) > 1
                if self.show_legend is None
                else self.show_legend,
                "colors": self.colors,
                "linestyle": self.linestyle,
                "linestyles": self.linestyles,
                "linewidth": self.linewidth,
                "linewidths": self.linewidths,
                "max_refresh_hz": self.max_refresh_hz,
                "x_major_tick_spacing": self.x_major_tick_spacing,
                "x_minor_tick_spacing": self.x_minor_tick_spacing,
            },
        )

    def _view_spec(self) -> LinePlotViewSpec:
        return self._line_binding().view_spec()

    def _panel_spec(self) -> PanelSpec:
        return self._line_binding().panel_spec()

    def _replace_message(self):
        series = self._series()
        return update_message(
            FieldReplace(
                field_id=self._field_id,
                values=np.array(
                    [[reader()] for reader in series.values()],
                    dtype=np.float32,
                ),
                coords={
                    "series": np.array(list(series.keys())),
                    "time": np.array([self._x_value()], dtype=np.float32),
                },
            )
        )


@dataclass(frozen=True, slots=True)
class LineWidget:
    """Reusable line widget accepted by ``source.add()``."""

    name: str
    read: SeriesReaders | None = None
    source: DataHandle | None = None
    x: Callable[[], float] | str | None = "time"
    by: str | None = None
    select: Mapping[str, Any] | None = None
    levels: Sequence[Any] = ()
    panel_id: str | None = None
    style: Mapping[str, Any] = field(default_factory=dict)

    def attach(self, context: WidgetAuthoringContext) -> LineHandle:
        style = dict(self.style)
        if self.read is not None:
            binding = TraceBinding(
                name=self.name,
                read=self.read,
                x=self.x if callable(self.x) else None,
                **style,
            )
            context._add_trace(binding)
            return LineHandle(binding._panel_id, binding)

        name_slug = slug(self.name)
        resolved_field_id = self.source._field_id if self.source is not None else None
        if resolved_field_id is None:
            raise ValueError("line(...) requires read=... or source=...")
        series_dim = self.by or (
            self.source._series_dim if self.source is not None else None
        )
        raw_selectors = (
            self.select
            if self.select is not None
            else (self.source._selectors if self.source is not None else {})
        )
        if (
            self.source is not None
            and self.source._unit is not None
            and "y_unit" not in style
        ):
            style["y_unit"] = self.source._unit
        panel_id = self.panel_id or f"{name_slug}-panel"
        context._add_binding(
            LinePlotBinding(
                field_id=resolved_field_id,
                view_id=f"{name_slug}_plot",
                panel_id=panel_id,
                title=style.pop("title", self.name),
                x_dim=self.x if isinstance(self.x, str) or self.x is None else "time",
                series_dim=series_dim,
                selectors={dim: bind(value) for dim, value in raw_selectors.items()},
                levels=self.levels,
                style=style,
            )
        )
        return LineHandle(panel_id, field_id=resolved_field_id)


__all__ = ["LinePlotBinding", "LineWidget", "SeriesReaders", "TraceBinding"]
