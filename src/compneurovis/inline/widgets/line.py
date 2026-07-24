"""Line widget declaration and AppSpec lowering.

Sampling/data production lives in ``SeriesProducer`` (``data_producers``); this
module keeps only the presentation binding and the authored ``Line`` widget.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

from compneurovis.core.app_spec import PANEL_KIND_LINE_PLOT, PanelSpec
from compneurovis.core.views import LinePlotViewSpec
from compneurovis.inline._ids import slug
from compneurovis.inline.compiler import FieldInput, WidgetContribution
from compneurovis.inline.data_producers import SeriesProducer, SeriesReaders
from compneurovis.inline.refs import DataRef, LineRef, bind
from compneurovis.inline.widgets.plotting import level_items, level_marker

if TYPE_CHECKING:
    from compneurovis.inline.widgets.api import WidgetAuthoringContext


@dataclass
class LineBinding:
    """Lower an already-declared data reference or operator into a line panel."""

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


# Presentation defaults previously carried as ``TraceBinding`` fields. Kept here
# so a callable-backed line still lowers to the same LinePlotViewSpec.
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
    "background_color": "w",
    "colors": {},
    "linestyle": "-",
    "linestyles": {},
    "linewidth": 2.0,
    "linewidths": {},
    "max_refresh_hz": None,
    "x_major_tick_spacing": None,
    "x_minor_tick_spacing": None,
}


@dataclass(frozen=True, slots=True)
class Line:
    """Reusable line widget accepted by ``source.add()``."""

    name: str
    read: SeriesReaders | None = None
    source: DataRef | None = None
    x: Callable[[], float] | str | None = "time"
    by: str | None = None
    select: Mapping[str, Any] | None = None
    levels: Sequence[Any] = ()
    panel_id: str | None = None
    style: Mapping[str, Any] = field(default_factory=dict)

    def attach(self, context: WidgetAuthoringContext) -> LineRef:
        if self.read is not None:
            return self._attach_series(context)
        return self._attach_source(context)

    def _attach_series(self, context: WidgetAuthoringContext) -> LineRef:
        given = dict(self.style)
        producer = SeriesProducer(
            name=self.name,
            read=self.read,
            x=self.x if callable(self.x) else None,
            y_unit=given.get("y_unit", "a.u."),
            max_samples=given.get("max_samples", 2400),
        )
        context._add_series(producer)

        style = {key: given.get(key, default) for key, default in _SERIES_STYLE_DEFAULTS.items()}
        series = producer._series()
        style["show_legend"] = given["show_legend"] if "show_legend" in given else len(series) > 1
        context._add_binding(
            LineBinding(
                field_id=producer._field_id,
                view_id=producer._view_id,
                panel_id=producer._panel_id,
                title=given.get("title") or self.name,
                x_dim="time",
                series_dim="series",
                levels=self.levels,
                field_builders=(lambda backend, _p=producer: _p._field_spec(),),
                style=style,
            )
        )
        return LineRef(producer._panel_id, producer)

    def _attach_source(self, context: WidgetAuthoringContext) -> LineRef:
        style = dict(self.style)
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
            LineBinding(
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
        return LineRef(panel_id, field_id=resolved_field_id)


__all__ = ["LineBinding", "Line", "SeriesReaders"]
