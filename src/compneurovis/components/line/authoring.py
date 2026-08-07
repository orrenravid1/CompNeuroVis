"""Line widget declaration through public authoring primitives."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

from compneurovis.inline._ids import slug
from compneurovis.inline.data_producers import SeriesReaders
from compneurovis.inline.refs import DataRef, LineRef
from compneurovis.inline.widgets.api import Widget

if TYPE_CHECKING:
    from compneurovis.inline.widgets.api import WidgetAuthoringContext


DEFAULT_LINE_MAX_REFRESH_HZ = 0.0


_SERIES_STYLE_DEFAULTS: dict[str, Any] = {
    "x_label": "Time",
    "y_label": "Value",
    "x_unit": "ms",
    "y_unit": "a.u.",
    "rolling_window": 500.0,
    "trim_to_rolling_window": True,
    "y_min": None,
    "y_max": None,
    "color": "k",
    "color_gradient": None,
    "background_color": "w",
    "colors": {},
    "linestyle": "-",
    "linestyles": {},
    "linewidth": 2.0,
    "linewidths": {},
    "max_refresh_hz": DEFAULT_LINE_MAX_REFRESH_HZ,
    "x_major_tick_spacing": None,
    "x_minor_tick_spacing": None,
}


@dataclass(frozen=True, slots=True)
class Line(Widget[LineRef]):
    """Reusable line widget accepted by ``source.add()``."""

    name: str
    read: SeriesReaders | None = None
    source: DataRef | None = None
    x: Callable[[], float] | str | None = "time"
    by: str | None = None
    select: Mapping[str, Any] | None = None
    panel_id: str | None = None
    style: Mapping[str, Any] = field(default_factory=dict)

    def declare(self, context: WidgetAuthoringContext) -> LineRef:
        if self.read is not None:
            return self._attach_series(context)
        return self._attach_source(context)

    def _attach_series(self, context: WidgetAuthoringContext) -> LineRef:
        given = dict(self.style)
        data = context.series(
            self.name,
            read=self.read,
            x=self.x if callable(self.x) else None,
            unit=given.get("y_unit", "a.u."),
            max_samples=given.get("max_samples", 2400),
        )
        properties = {
            key: given.get(key, default)
            for key, default in _SERIES_STYLE_DEFAULTS.items()
        }
        series_count = len(self.read) if isinstance(self.read, Mapping) else 1
        properties["show_legend"] = given.get("show_legend", series_count > 1)
        if properties["rolling_window"] is not None:
            context.require_retention(
                data,
                append_dim="time",
                min_duration=float(properties["rolling_window"]),
            )
        title = given.get("title") or self.name
        max_refresh_hz = properties.pop(
            "max_refresh_hz", DEFAULT_LINE_MAX_REFRESH_HZ
        )
        if max_refresh_hz is None:
            max_refresh_hz = DEFAULT_LINE_MAX_REFRESH_HZ
        panel = context.view(
            "line_plot",
            self.name,
            inputs={"data": data},
            properties={
                "x_dim": "time",
                "series_dim": "series",
                "selectors": {},
                **properties,
            },
            title=title,
            panel_id=self.panel_id or f"{slug(self.name)}-panel",
            max_refresh_hz=max_refresh_hz,
        )
        return LineRef(panel.id, field_id=data._field_id)

    def _attach_source(self, context: WidgetAuthoringContext) -> LineRef:
        if self.source is None:
            raise ValueError("line(...) requires read=... or source=...")
        style = dict(self.style)
        if self.source._unit is not None and "y_unit" not in style:
            style["y_unit"] = self.source._unit
        title = style.pop("title", self.name)
        max_refresh_hz = style.pop(
            "max_refresh_hz", DEFAULT_LINE_MAX_REFRESH_HZ
        )
        if max_refresh_hz is None:
            max_refresh_hz = DEFAULT_LINE_MAX_REFRESH_HZ
        series_dim = self.by or self.source._series_dim
        selectors = (
            self.select if self.select is not None else self.source._selectors
        )
        x_dim = (
            self.x
            if isinstance(self.x, str) or self.x is None
            else "time"
        )
        rolling_window = style.get(
            "rolling_window", _SERIES_STYLE_DEFAULTS["rolling_window"]
        )
        if x_dim is not None and rolling_window is not None:
            context.require_retention(
                self.source,
                append_dim=x_dim,
                min_duration=float(rolling_window),
            )
        panel = context.view(
            "line_plot",
            self.name,
            inputs={"data": self.source},
            properties={
                "x_dim": x_dim,
                "series_dim": series_dim,
                "selectors": dict(selectors),
                **style,
            },
            title=title,
            panel_id=self.panel_id or f"{slug(self.name)}-panel",
            max_refresh_hz=max_refresh_hz,
        )
        return LineRef(panel.id, field_id=self.source._field_id)


__all__ = ["Line", "SeriesReaders"]
