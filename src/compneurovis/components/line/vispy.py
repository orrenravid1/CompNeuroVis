"""Vispy/PyQtGraph implementation of the Line component."""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pyqtgraph as pg
from PyQt6 import QtCore

from compneurovis.core._immutability import FrozenDict
from compneurovis.core.field import Field
from compneurovis.core.runtime.performance import perf_log
from compneurovis.core.views import ViewSpec, ValueOrBinding
from compneurovis.frontends.vispy.bindings import binding_key, resolve_binding
from compneurovis.frontends.vispy.plot2d.host import Plot2DHostPanel
from compneurovis.frontends.vispy.registries.render_configs import ViewRenderConfig
from compneurovis.frontends.vispy.plot2d.styles import (
    freeze_series_style as _freeze_series_style,
    series_style as _series_style,
)

SeriesStyle = Any

@dataclass(frozen=True, slots=True)
class LinePlotRenderConfig(ViewRenderConfig):
    """Frontend render-config, not an authored view: built by ``LinePlotHost`` from
    a ``ViewSpec(kind="line_plot")``. No ``panel_kind``/``kind``."""

    field_id: str = ""
    operator_id: str | None = None
    x_dim: str | None = None
    series_dim: str | None = None
    selectors: Mapping[str, Any] = field(default_factory=FrozenDict)
    x_label: str = "x"
    y_label: str = "y"
    x_unit: str = ""
    y_unit: str = ""
    # matplotlib-style appearance. Singular props (``color``/``linestyle``/
    # ``linewidth``) are the default for the sole line, or for every series. The
    # plurals override per series: a ``{label: value}`` map, or a sequence cycled
    # by series index. ``linestyle`` takes matplotlib strings: "-", "--", "-.", ":".
    color: ValueOrBinding = "k"
    background_color: ValueOrBinding = "w"
    show_legend: bool = True
    colors: SeriesStyle = field(default_factory=FrozenDict)
    linestyle: ValueOrBinding = "-"
    linestyles: SeriesStyle = field(default_factory=FrozenDict)
    linewidth: ValueOrBinding = 2.0
    linewidths: SeriesStyle = field(default_factory=FrozenDict)
    rolling_window: float | None = None
    trim_to_rolling_window: bool = False
    max_refresh_hz: float | None = None
    y_min: float | None = None
    y_max: float | None = None
    x_major_tick_spacing: float | None = None
    x_minor_tick_spacing: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "selectors", FrozenDict(self.selectors))
        object.__setattr__(self, "colors", _freeze_series_style(self.colors))
        object.__setattr__(self, "linestyles", _freeze_series_style(self.linestyles))
        object.__setattr__(self, "linewidths", _freeze_series_style(self.linewidths))

LINE_PLOT_PAINT_LOG_THRESHOLD_MS = 5.0
LINE_PLOT_PAINT_FORCE_LOG_THRESHOLD_MS = 24.0
LINE_PLOT_PAINT_LOG_INTERVAL_S = 0.5

# matplotlib linestyle strings -> Qt pen styles.
_QT_PEN_STYLES = {
    "-": QtCore.Qt.PenStyle.SolidLine, "solid": QtCore.Qt.PenStyle.SolidLine,
    "--": QtCore.Qt.PenStyle.DashLine, "dashed": QtCore.Qt.PenStyle.DashLine,
    ":": QtCore.Qt.PenStyle.DotLine, "dotted": QtCore.Qt.PenStyle.DotLine,
    "-.": QtCore.Qt.PenStyle.DashDotLine, "dashdot": QtCore.Qt.PenStyle.DashDotLine,
}


def _make_pen(color: Any, width: Any, linestyle: Any):
    """Build a pyqtgraph pen from matplotlib-style color / width / linestyle."""
    style = _QT_PEN_STYLES.get(str(linestyle), QtCore.Qt.PenStyle.SolidLine)
    return pg.mkPen(color, width=float(width), style=style)


def _manual_tick_levels(xmin: float, xmax: float, major: float | None, minor: float | None):
    if major is None:
        return None
    if xmax < xmin:
        xmin, xmax = xmax, xmin
    major_ticks = _build_tick_values(xmin, xmax, major)
    minor_ticks = _build_tick_values(xmin, xmax, minor) if minor is not None and minor > 0 else []
    major_values = {round(value, 9) for value in major_ticks}
    minor_ticks = [value for value in minor_ticks if round(value, 9) not in major_values]
    return [
        [(value, _format_tick_label(value, major)) for value in major_ticks],
        [(value, "") for value in minor_ticks],
    ]


def _build_tick_values(xmin: float, xmax: float, spacing: float | None) -> list[float]:
    if spacing is None or spacing <= 0:
        return []
    start = math.ceil((xmin - 1e-9) / spacing) * spacing
    values = []
    value = start
    while value <= xmax + 1e-9:
        values.append(round(value, 9))
        value += spacing
    return values


def _format_tick_label(value: float, spacing: float) -> str:
    if spacing >= 1 and abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    decimals = max(0, min(6, int(math.ceil(-math.log10(spacing))) if spacing < 1 else 0))
    text = f"{value:.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


class LinePlotCanvas(pg.PlotWidget):
    _DOWNSAMPLING_METHOD = "peak"

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
        self._perf_panel_id = perf_panel_id
        self._perf_view_id = perf_view_id
        self._resolved_title = ""
        self.setBackground("w")
        self._plot_item = self.plot([], [], pen="k")
        self._configure_data_item(self._plot_item)
        self._series_items: dict[str, pg.PlotDataItem] = {}
        self._legend_signature: tuple[str, ...] | None = None
        # Per-refresh fast-path caches. Each gates one piece of work that does
        # not depend on the data tail. Cleared via _clear_render_caches() when
        # structure changes such as view None, series clearing, or renderer swaps.
        self._cache_structural_signature: tuple[Any, ...] | None = None
        self._cache_pens: dict[str, tuple[Any, Any]] = {}
        self._cache_y_range_applied: tuple[float | None, float | None] | None = None
        self._cache_x_range_applied: tuple[float, float] | None = None
        self._cache_tick_signature: tuple[Any, ...] | str | None = None
        self._cache_background: Any = None
        self._last_slow_paint_log_s = 0.0
        self._slow_paint_count = 0
        self._slow_paint_max_ms = 0.0

    def _configure_data_item(self, item: pg.PlotDataItem) -> None:
        # Let pyqtgraph clip and downsample to the visible viewport so line-plot
        # redraw cost does not grow linearly with retained history or window size.
        item.setClipToView(True)
        item.setDownsampling(auto=True, method=self._DOWNSAMPLING_METHOD)
        # This panel already strips non-finite samples before setData().
        item.setSkipFiniteCheck(True)

    @property
    def resolved_title(self) -> str:
        return self._resolved_title

    def _set_resolved_title(self, title: str) -> None:
        self._resolved_title = str(title)
        self.setTitle(self._resolved_title if self._show_internal_title else "")

    def refresh(
        self,
        view: LinePlotRenderConfig | None,
        field: Field | None,
        values: dict[str, Any],
    ) -> None:
        if view is None or field is None:
            self._refresh_empty()
            return

        self._apply_background(view, values)

        sliced = self._select_field_for_view(view, field, values)
        if sliced is None:
            return

        x_dim = view.x_dim or sliced.dims[-1]
        if view.series_dim is not None:
            self._plot_item.setData([], [])
            self._refresh_series(view, sliced, x_dim, values)
        else:
            self._refresh_single_series(view, sliced, x_dim, values, source_field_id=field.id)

    def paintEvent(self, event) -> None:
        started = time.monotonic()
        super().paintEvent(event)
        now = time.monotonic()
        duration_ms = round((now - started) * 1000.0, 3)
        if duration_ms >= LINE_PLOT_PAINT_LOG_THRESHOLD_MS:
            self._slow_paint_count += 1
            self._slow_paint_max_ms = max(self._slow_paint_max_ms, duration_ms)
        if (
            self._slow_paint_count
            and (
                duration_ms >= LINE_PLOT_PAINT_FORCE_LOG_THRESHOLD_MS
                or now - self._last_slow_paint_log_s >= LINE_PLOT_PAINT_LOG_INTERVAL_S
            )
        ):
            perf_log(
                "line_plot",
                "paint",
                panel_id=self._perf_panel_id,
                view_id=self._perf_view_id,
                width_px=self.width(),
                height_px=self.height(),
                duration_ms=duration_ms,
                slow_paint_count=self._slow_paint_count,
                slow_paint_max_ms=round(self._slow_paint_max_ms, 3),
            )
            self._last_slow_paint_log_s = now
            self._slow_paint_count = 0
            self._slow_paint_max_ms = 0.0

    def _refresh_empty(self) -> None:
        self._clear_series()
        self._plot_item.setData([], [])
        self._set_resolved_title("")
        self._reset_view_ranges()
        self._clear_render_caches()

    def _apply_background(self, view: LinePlotRenderConfig, values: dict[str, Any]) -> None:
        background = resolve_binding(view.background_color, values)
        if background is not None and background != self._cache_background:
            self.setBackground(background)
            self._cache_background = background

    @staticmethod
    def _resolved_view_title(
        view: LinePlotRenderConfig,
        values: dict[str, Any],
        fallback: str,
    ) -> str:
        title = resolve_binding(view.title, values)
        if title is None or title == "":
            title = fallback
        selector_titles: list[str] = []
        for selector in view.selectors.values():
            if binding_key(selector) is None:
                continue
            resolved = resolve_binding(selector, values)
            if resolved is None:
                continue
            if isinstance(resolved, (list, tuple, np.ndarray)):
                selected = np.asarray(resolved).reshape(-1).tolist()
                if not selected:
                    continue
                selector_titles.append(
                    str(selected[0])
                    if len(selected) == 1
                    else f"{len(selected)} selected"
                )
            else:
                selector_titles.append(str(resolved))
        base = str(title)
        if not selector_titles:
            return base
        return f"{base} — {' / '.join(selector_titles)}"

    def _select_field_for_view(
        self,
        view: LinePlotRenderConfig,
        field: Field,
        values: dict[str, Any],
    ) -> Field | None:
        resolved_selectors = {}
        for dim, selector in view.selectors.items():
            resolved = resolve_binding(selector, values)
            if resolved is None:
                self._plot_item.setData([], [])
                return None
            filtered = self._filter_selector_for_field(
                field,
                dim,
                resolved,
                preserve_dimension=dim in {view.series_dim, view.x_dim},
            )
            if filtered is None:
                self._clear_series()
                self._plot_item.setData([], [])
                return None
            resolved_selectors[dim] = filtered

        try:
            return field.select(resolved_selectors)
        except KeyError:
            self._clear_series()
            self._plot_item.setData([], [])
            return None

    @staticmethod
    def _filter_selector_for_field(
        field: Field,
        dim: str,
        selector: Any,
        *,
        preserve_dimension: bool,
    ) -> Any | None:
        coord = field.coord(dim)
        if isinstance(selector, str):
            return selector if np.any(coord.astype(str) == selector) else None
        if isinstance(selector, (list, tuple, np.ndarray)):
            selector_array = np.asarray(selector)
            if selector_array.ndim != 1 or selector_array.size == 0:
                return None if selector_array.size == 0 else selector
            if np.issubdtype(selector_array.dtype, np.integer) or np.issubdtype(selector_array.dtype, np.floating):
                return selector
            coord_labels = set(coord.astype(str).tolist())
            filtered = [value for value in selector_array.astype(str).tolist() if value in coord_labels]
            if not filtered:
                return None
            if len(filtered) == 1 and not preserve_dimension:
                return filtered[0]
            return filtered
        return selector

    def _refresh_single_series(
        self,
        view: LinePlotRenderConfig,
        field: Field,
        x_dim: str,
        values: dict[str, Any],
        *,
        source_field_id: str,
    ) -> None:
        self._clear_series()
        if len(field.dims) != 1 or field.dims[0] != x_dim:
            raise ValueError(f"LinePlotRenderConfig '{view.id}' must resolve to a 1D field along '{x_dim}'")

        x = np.asarray(field.coord(x_dim), dtype=np.float32)
        y = np.asarray(field.values, dtype=np.float32)
        x, y = self._trim_line_data(view, x, y)
        title = self._resolved_view_title(view, values, source_field_id)
        structural_sig = (
            "single", view.id, view.x_label or x_dim, view.x_unit,
            view.y_label, view.y_unit, title,
        )
        self._apply_single_series_structure(
            structural_sig,
            x_label=view.x_label or x_dim,
            x_unit=view.x_unit,
            y_label=view.y_label,
            y_unit=view.y_unit,
            title=title,
        )
        self._apply_single_pen(
            resolve_binding(view.color, values),
            resolve_binding(view.linewidth, values),
            resolve_binding(view.linestyle, values),
        )
        self._plot_item.setData(x, y)
        self._apply_view_ranges(view, x)

    def _apply_single_series_structure(
        self,
        structural_sig: tuple[Any, ...],
        *,
        x_label: str,
        x_unit: str | None,
        y_label: str,
        y_unit: str | None,
        title: str,
    ) -> None:
        if structural_sig == self._cache_structural_signature:
            return
        self.setLabel("bottom", x_label, x_unit)
        self.setLabel("left", y_label, y_unit)
        self._set_resolved_title(title)
        self._cache_structural_signature = structural_sig
        self._cache_pens.clear()

    def _apply_single_pen(self, color, width, linestyle) -> None:
        key = (color, width, str(linestyle))
        cached_pen = self._cache_pens.get("__single__")
        if cached_pen is None or cached_pen[0] != key:
            pen = _make_pen(color, width, linestyle)
            self._cache_pens["__single__"] = (key, pen)
            self._plot_item.setPen(pen)

    def _refresh_series(self, view: LinePlotRenderConfig, field: Field, x_dim: str, values: dict[str, Any]) -> None:
        series_dim = view.series_dim
        if series_dim is None:
            raise ValueError("series_dim is required for multi-series refresh")
        x, series_values, series_labels = self._series_plot_data(view, field, x_dim, series_dim)
        self._apply_series_structure(view, field.id, x_dim, series_labels, values)
        self._remove_stale_series(series_labels)
        range_x = self._update_series_items(view, x, series_values, series_labels, values)
        self._update_series_legend(series_labels)
        self._apply_view_ranges(view, range_x)

    def _series_plot_data(
        self,
        view: LinePlotRenderConfig,
        field: Field,
        x_dim: str,
        series_dim: str,
    ) -> tuple[np.ndarray, np.ndarray, list[str]]:
        if set(field.dims) != {series_dim, x_dim} or field.values.ndim != 2:
            raise ValueError(
                f"LinePlotRenderConfig '{view.id}' with series_dim='{series_dim}' must resolve to a 2D field over ({series_dim}, {x_dim})"
            )
        axis_map = {dim: idx for idx, dim in enumerate(field.dims)}
        values = field.values
        if values.dtype != np.float32:
            values = np.asarray(values, dtype=np.float32)
        if field.dims != (series_dim, x_dim):
            values = np.transpose(values, axes=(axis_map[series_dim], axis_map[x_dim]))

        x_coord = field.coord(x_dim)
        x = x_coord if x_coord.dtype == np.float32 else np.asarray(x_coord, dtype=np.float32)
        series_labels = [str(label) for label in field.coord(series_dim)]
        x, values = self._trim_series_data(view, x, values)
        return x, values, series_labels

    def _apply_series_structure(
        self,
        view: LinePlotRenderConfig,
        field_id: str,
        x_dim: str,
        series_labels: list[str],
        values: dict[str, Any],
    ) -> None:
        title = self._resolved_view_title(view, values, field_id)
        structural_sig = (
            "series", view.id, view.x_label or x_dim, view.x_unit,
            view.y_label, view.y_unit, title, view.show_legend,
            tuple(series_labels),
        )
        if structural_sig == self._cache_structural_signature:
            return
        self.setLabel("bottom", view.x_label or x_dim, view.x_unit)
        self.setLabel("left", view.y_label, view.y_unit)
        self._set_resolved_title(title)
        self._ensure_legend(view.show_legend)
        self._cache_structural_signature = structural_sig
        self._cache_pens.clear()

    def _ensure_legend(self, enabled: bool) -> None:
        if enabled and self.plotItem.legend is None:
            self.addLegend(offset=(10, 10))
        elif not enabled and self.plotItem.legend is not None:
            self.plotItem.legend.scene().removeItem(self.plotItem.legend)
            self.plotItem.legend = None
            self._legend_signature = None

    def _remove_stale_series(self, series_labels: list[str]) -> None:
        stale = set(self._series_items.keys()) - set(series_labels)
        for label in stale:
            self.removeItem(self._series_items[label])
            del self._series_items[label]
            self._cache_pens.pop(label, None)

    def _update_series_items(
        self,
        view: LinePlotRenderConfig,
        x: np.ndarray,
        series_values: np.ndarray,
        series_labels: list[str],
        values: dict[str, Any],
    ) -> np.ndarray:
        visible_xmin: float | None = None
        visible_xmax: float | None = None
        for idx, label in enumerate(series_labels):
            pen, pen_changed = self._series_pen(view, label, idx, values)
            item = self._series_items.get(label)
            if item is None:
                item = self.plot([], [], pen=pen)
                self._configure_data_item(item)
                self._series_items[label] = item
            elif pen_changed:
                item.setPen(pen)

            series_x, series_y = self._finite_line_data(x, series_values[idx])
            item.setData(series_x, series_y)
            if len(series_x):
                series_xmin = float(np.min(series_x))
                series_xmax = float(np.max(series_x))
                visible_xmin = series_xmin if visible_xmin is None else min(visible_xmin, series_xmin)
                visible_xmax = series_xmax if visible_xmax is None else max(visible_xmax, series_xmax)

        if visible_xmin is None or visible_xmax is None:
            return np.asarray([], dtype=np.float32)
        return np.asarray([visible_xmin, visible_xmax], dtype=np.float32)

    def _series_pen(self, view: LinePlotRenderConfig, label: str, idx: int, values: dict[str, Any]):
        color = resolve_binding(_series_style(view.colors, label, idx, view.color), values)
        width = resolve_binding(_series_style(view.linewidths, label, idx, view.linewidth), values)
        linestyle = resolve_binding(_series_style(view.linestyles, label, idx, view.linestyle), values)
        key = (color, width, str(linestyle))
        cached = self._cache_pens.get(label)
        if cached is not None and cached[0] == key:
            return cached[1], False
        pen = _make_pen(color, width, linestyle)
        self._cache_pens[label] = (key, pen)
        return pen, True

    def _series_color(self, view: LinePlotRenderConfig, label: str, idx: int):
        return _series_style(view.colors, label, idx, view.color)

    def _update_series_legend(self, series_labels: list[str]) -> None:
        if self.plotItem.legend is not None:
            legend_signature = tuple(series_labels)
            if legend_signature != self._legend_signature:
                self.plotItem.legend.clear()
                for label in series_labels:
                    self.plotItem.legend.addItem(self._series_items[label], label)
                self._legend_signature = legend_signature
        else:
            self._legend_signature = None

    def _trim_line_data(self, view: LinePlotRenderConfig, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if not view.trim_to_rolling_window or view.rolling_window is None or len(x) == 0:
            return self._finite_line_data(x, y)
        mask = self._rolling_window_mask(x, float(view.rolling_window))
        return self._finite_line_data(x[mask], y[mask])

    def _trim_series_data(
        self,
        view: LinePlotRenderConfig,
        x: np.ndarray,
        values: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        if not view.trim_to_rolling_window or view.rolling_window is None or len(x) == 0:
            return x, values
        mask = self._rolling_window_mask(x, float(view.rolling_window))
        return x[mask], values[:, mask]

    def _finite_line_data(self, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        mask = np.isfinite(x) & np.isfinite(y)
        return x[mask], y[mask]

    def _rolling_window_mask(self, x: np.ndarray, window: float) -> np.ndarray:
        xmin = float(x[-1]) - window
        mask = x >= xmin
        if np.any(mask):
            first_visible = int(np.argmax(mask))
            if first_visible > 0:
                # Keep the sample immediately before the window so the plotted line
                # enters at the left boundary instead of appearing after a gap.
                mask[first_visible - 1] = True
        return mask

    def _apply_view_ranges(self, view: LinePlotRenderConfig, x: np.ndarray) -> None:
        self._apply_y_range(view)
        xmin, xmax = self._apply_x_range(view, x)
        self._apply_tick_spacing(view, xmin, xmax)

    def _apply_y_range(self, view: LinePlotRenderConfig) -> None:
        vb = self.plotItem.getViewBox()
        if view.y_min is not None or view.y_max is not None:
            y_target = (view.y_min, view.y_max)
            if y_target != self._cache_y_range_applied:
                vb.enableAutoRange(y=False)
                vb.setLimits(yMin=view.y_min, yMax=view.y_max)
                if view.y_min is not None and view.y_max is not None:
                    vb.setYRange(float(view.y_min), float(view.y_max), padding=0)
                self._cache_y_range_applied = y_target
        else:
            if self._cache_y_range_applied is not None:
                vb.enableAutoRange(y=True)
                vb.setLimits(yMin=None, yMax=None)
                self._cache_y_range_applied = None

    def _apply_x_range(self, view: LinePlotRenderConfig, x: np.ndarray) -> tuple[float, float]:
        vb = self.plotItem.getViewBox()
        if view.rolling_window is not None and len(x):
            data_xmin = float(np.min(x))
            data_xmax = float(np.max(x))
            xmin = max(data_xmin, data_xmax - float(view.rolling_window))
            applied = (xmin, data_xmax) if data_xmax > xmin else (xmin, xmin + max(float(view.rolling_window), 1e-6))
            if applied != self._cache_x_range_applied:
                vb.enableAutoRange(x=False)
                vb.setXRange(applied[0], applied[1], padding=0)
                self._cache_x_range_applied = applied
            return applied
        else:
            if self._cache_x_range_applied is not None:
                vb.enableAutoRange(x=True)
                vb.setLimits(xMin=None, xMax=None)
                self._cache_x_range_applied = None
            if len(x):
                return float(np.min(x)), float(np.max(x))
            return 0.0, 0.0

    def _reset_view_ranges(self) -> None:
        vb = self.plotItem.getViewBox()
        vb.enableAutoRange(x=True, y=True)
        vb.setLimits(xMin=None, xMax=None, yMin=None, yMax=None)
        self._reset_tick_spacing()
        self._cache_x_range_applied = None
        self._cache_y_range_applied = None
        self._cache_tick_signature = None

    def _apply_tick_spacing(self, view: LinePlotRenderConfig, xmin: float, xmax: float) -> None:
        axis = self.plotItem.getAxis("bottom")
        if view.x_major_tick_spacing is not None or view.x_minor_tick_spacing is not None:
            major = view.x_major_tick_spacing
            minor = view.x_minor_tick_spacing
            if minor is None and major is not None:
                minor = major / 5.0
            # Tick set changes only when the visible bounds cross the smallest
            # spacing that can add or remove a visible tick.
            signature_spacing = minor if minor is not None and minor > 0 else major
            if signature_spacing and signature_spacing > 0:
                grid_lo = math.floor((xmin - 1e-9) / signature_spacing)
                grid_hi = math.ceil((xmax + 1e-9) / signature_spacing)
            else:
                grid_lo, grid_hi = xmin, xmax
            sig = (major, minor, grid_lo, grid_hi)
            if sig != self._cache_tick_signature:
                axis.setTicks(_manual_tick_levels(xmin, xmax, major, minor))
                self._cache_tick_signature = sig
        else:
            if self._cache_tick_signature != "auto":
                self._reset_tick_spacing()
                self._cache_tick_signature = "auto"

    def _reset_tick_spacing(self) -> None:
        axis = self.plotItem.getAxis("bottom")
        axis.setTicks(None)
        axis.setTickSpacing()

    def _clear_series(self) -> None:
        if self._series_items:
            for item in self._series_items.values():
                self.removeItem(item)
            self._series_items.clear()
        if self.plotItem.legend is not None:
            self.plotItem.legend.clear()
        self._legend_signature = None

    def _clear_render_caches(self) -> None:
        self._cache_structural_signature = None
        self._cache_pens.clear()
        self._cache_y_range_applied = None
        self._cache_x_range_applied = None
        self._cache_tick_signature = None
        self._cache_background = None


class LinePlotHost(Plot2DHostPanel):
    """Standalone host: adapts ``ViewSpec(kind="line_plot")`` onto the visual.

    A sibling of :class:`BarPlotHost`. Reconstructs the typed
    ``LinePlotRenderConfig`` from the view's raw ``properties`` (bindings left intact)
    and hands the real ``values`` to the shared visual, so every feature --
    levels, selectors, per-series styling -- resolves exactly as it does natively.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(canvas_factory=LinePlotCanvas, **kwargs)

    def refresh(
        self,
        view: ViewSpec,
        inputs: Mapping[str, Any],
        properties: Mapping[str, Any],
        values: Mapping[str, Any] | None = None,
    ) -> None:
        props = dict(view.properties)
        props.pop("max_refresh_hz", None)  # carried at the ViewSpec level
        line_view = LinePlotRenderConfig(
            id=view.id,
            title=view.title,
            field_id=view.inputs.get("data", ""),
            max_refresh_hz=view.max_refresh_hz,
            **props,
        )
        self._render(line_view, inputs.get("data"), dict(values or {}))



__all__ = ["LinePlotHost", "LinePlotRenderConfig"]
