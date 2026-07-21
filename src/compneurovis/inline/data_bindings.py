"""Data producers owned by generic source-level widgets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence, TypeAlias

import numpy as np

from compneurovis.core.app_spec import PANEL_KIND_VIEW_3D, PanelSpec
from compneurovis.core.field import FieldSpec
from compneurovis.core.geometry import GridGeometrySpec
from compneurovis.core.messages import FieldAppend, FieldReplace, update_message
from compneurovis.core.operators import GridSliceOperatorSpec
from compneurovis.core.views import LinePlotViewSpec, SurfaceViewSpec
from compneurovis.inline._ids import slug
from compneurovis.inline.handles import bind, binding_key
from compneurovis.inline.widget_contributions import WidgetContribution
from compneurovis.inline.widget_specs import LinePlotWidget


SeriesReaders: TypeAlias = (
    Callable[[], float]
    | Mapping[str, Callable[[], float]]
)


@dataclass
class ArrayFieldBinding:
    """One-dimensional static or callable-backed field."""

    field_id: str
    dim: str
    labels: tuple[str, ...]
    values: Any = None
    read: Callable[[], Any] | None = None
    unit: str | None = None

    def resolve(self) -> np.ndarray:
        raw = self.read() if self.read is not None else self.values
        array = np.asarray(raw, dtype=np.float32).reshape(-1)
        if array.size != len(self.labels):
            raise ValueError(
                f"field {self.field_id!r} expects {len(self.labels)} values "
                f"over dim {self.dim!r}, got {array.size}"
            )
        return array

    def field_spec(self) -> FieldSpec:
        return FieldSpec(
            id=self.field_id,
            initial_values=self.resolve(),
            dims=(self.dim,),
            coords={self.dim: np.asarray(self.labels)},
            unit=self.unit,
        )

    def replace_payload(self) -> FieldReplace:
        return FieldReplace(
            field_id=self.field_id,
            values=self.resolve(),
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
        series_count = len(self._series())
        values = np.array(samples, dtype=np.float32).reshape(
            len(x_values),
            series_count,
        ).T
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
        widget = self._line_widget()
        return WidgetContribution(
            fields=(self._field_spec(),),
            views=(widget.view_spec(),),
            panel=widget.panel_spec(),
        )

    def _line_widget(self) -> LinePlotWidget:
        series = self._series()
        return LinePlotWidget(
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
                "show_legend": (
                    len(series) > 1
                    if self.show_legend is None
                    else self.show_legend
                ),
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
        return self._line_widget().view_spec()

    def _panel_spec(self) -> PanelSpec:
        return self._line_widget().panel_spec()

    def _replace_message(self):
        series = self._series()
        values = np.array(
            [[reader()] for reader in series.values()],
            dtype=np.float32,
        )
        return update_message(
            FieldReplace(
                field_id=self._field_id,
                values=values,
                coords={
                    "series": np.array(list(series.keys())),
                    "time": np.array([self._x_value()], dtype=np.float32),
                },
            )
        )


@dataclass
class SurfaceBinding:
    """Two-dimensional static or callable-backed surface field."""

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

    def _coords(
        self,
        values: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
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

    def contribution(self, backend: Any = None) -> WidgetContribution:
        del backend
        return WidgetContribution(
            fields=(self._field_spec(),),
            geometries=(self._geometry_spec(),),
            views=(self._view_spec(),),
            panel=self._panel_spec(),
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
        kwargs = {
            key: bind(value)
            for key, value in self.view_kwargs.items()
        }
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

    def contribution(self, backend: Any = None) -> WidgetContribution:
        del backend
        widget = self._line_widget()
        return WidgetContribution(
            operators=(self._operator_spec(),),
            views=(widget.view_spec(),),
            panel=widget.panel_spec(),
        )

    def _operator_spec(self) -> GridSliceOperatorSpec:
        return GridSliceOperatorSpec(
            id=self._operator_id,
            field_id=self.surface._field_id,
            geometry_id=self.surface._geometry_id,
            axis_value_key=binding_key(self.axis),
            position_value_key=binding_key(self.position),
            **{
                key: bind(value)
                for key, value in self.overlay_kwargs.items()
            },
        )

    def _line_widget(self) -> LinePlotWidget:
        kwargs = {
            key: bind(value)
            for key, value in self.line_kwargs.items()
        }
        title = kwargs.pop("title", self.name)
        levels = kwargs.pop("levels", ())
        x_dim = kwargs.pop("x_dim", None)
        return LinePlotWidget(
            operator_id=self._operator_id,
            view_id=self._view_id,
            panel_id=self._panel_id,
            title=title,
            x_dim=x_dim,
            levels=levels,
            style=kwargs,
        )

    def _view_spec(self) -> LinePlotViewSpec:
        return self._line_widget().view_spec()

    def _panel_spec(self) -> PanelSpec:
        return self._line_widget().panel_spec()


@dataclass
class DerivedValueBinding:
    """Callable-backed runtime value with an independent refresh cadence."""

    name: str
    fn: Callable[[], Any]
    max_refresh_hz: float | None = 10.0
    initial: Any = None
    _last_eval_s: float = field(
        init=False,
        default=float("-inf"),
    )

    def due(self, now: float) -> bool:
        interval = (
            1.0 / self.max_refresh_hz
            if self.max_refresh_hz and self.max_refresh_hz > 0
            else 0.0
        )
        return (now - self._last_eval_s) >= interval

    def evaluate(self, now: float) -> Any:
        self._last_eval_s = now
        return self.fn()


__all__ = [
    "ArrayFieldBinding",
    "DerivedValueBinding",
    "GridSliceBinding",
    "SeriesReaders",
    "SurfaceBinding",
    "TraceBinding",
]
