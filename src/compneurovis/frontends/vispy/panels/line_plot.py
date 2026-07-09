from __future__ import annotations

import math
import time
from typing import Any

import numpy as np
import pyqtgraph as pg
from PyQt6 import QtWidgets

from compneurovis.core._perf import perf_log
from compneurovis.core.field import Field
from compneurovis.core.views import BarPlotViewSpec, LinePlotViewSpec
from compneurovis.frontends.vispy.view_inputs.bindings import resolve_binding

LINE_PLOT_PAINT_LOG_THRESHOLD_MS = 5.0
LINE_PLOT_PAINT_FORCE_LOG_THRESHOLD_MS = 24.0
LINE_PLOT_PAINT_LOG_INTERVAL_S = 0.5


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


class LinePlotPanel(pg.PlotWidget):
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
        # Bar rendering (BarPlotViewSpec) and reference-line overlays (levels).
        self._bar_item: pg.BarGraphItem | None = None
        self._bar_tick_signature: tuple[str, ...] | None = None
        self._bar_x_range: tuple[float, float] | None = None
        self._bar_y_applied: tuple[float | None, float | None] | bool | None = None
        self._level_items: list[pg.InfiniteLine] = []
        self._level_sigs: dict[int, tuple[Any, ...]] = {}
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
        view: LinePlotViewSpec | BarPlotViewSpec | None,
        field: Field | None,
        values: dict[str, Any],
    ) -> None:
        if isinstance(view, BarPlotViewSpec):
            self._refresh_bars(view, field, values)
            self._refresh_levels(view, values)
            return

        if view is None or field is None:
            self._refresh_empty()
            return

        self._apply_background(view, values)

        sliced = self._select_field_for_view(view, field, values)
        if sliced is None:
            self._refresh_levels(view, values)
            return

        x_dim = view.x_dim or sliced.dims[-1]
        if view.series_dim is not None:
            self._plot_item.setData([], [])
            self._refresh_series(view, sliced, x_dim, values)
        else:
            self._refresh_single_trace(view, sliced, x_dim, values, source_field_id=field.id)
        self._refresh_levels(view, values)

    def _refresh_bars(self, view: BarPlotViewSpec, field: Field | None, values: dict[str, Any]) -> None:
        background = resolve_binding(view.background_color, values)
        if background is not None and background != self._cache_background:
            self.setBackground(background)
            self._cache_background = background
        if field is None:
            if self._bar_item is not None:
                self._bar_item.setOpts(height=np.zeros(0))
            return
        cat_dim = view.category_dim if view.category_dim in field.dims else (field.dims[0] if field.dims else None)
        heights = np.asarray(field.values, dtype=np.float64).reshape(-1)
        n = len(heights)
        labels = (
            [str(label) for label in field.coord(cat_dim)]
            if cat_dim is not None
            else [str(i) for i in range(n)]
        )
        structural = tuple(labels)
        if self._bar_item is None or structural != self._bar_tick_signature:
            # Categories changed (rare): rebuild bar geometry, ticks, labels, ranges.
            x = np.arange(n, dtype=np.float64)
            brush = resolve_binding(view.bar_color, values)
            if self._bar_item is None:
                self._bar_item = pg.BarGraphItem(x=x, height=heights, width=0.8, brush=brush)
                self.addItem(self._bar_item)
            else:
                self._bar_item.setOpts(x=x, height=heights, width=0.8, brush=brush)
            self.getAxis("bottom").setTicks([[(i, label) for i, label in enumerate(labels)]])
            self.setLabel("bottom", view.x_label)
            self.setLabel("left", view.y_label, view.y_unit)
            self._set_resolved_title(str(resolve_binding(view.title, values) or ""))
            self._bar_tick_signature = structural
            vb = self.plotItem.getViewBox()
            x_range = (-0.6, max(0.4, n - 0.4))
            if x_range != self._bar_x_range:
                vb.setXRange(*x_range, padding=0)
                self._bar_x_range = x_range
            y_target = (view.y_min, view.y_max)
            if view.y_min is not None and view.y_max is not None:
                if y_target != self._bar_y_applied:
                    vb.setYRange(float(view.y_min), float(view.y_max), padding=0)
                    self._bar_y_applied = y_target
            elif self._bar_y_applied is not False:
                # Enable y autorange once; the viewbox rescales passively thereafter.
                vb.enableAutoRange(y=True)
                self._bar_y_applied = False
        else:
            # Hot path: only the bar heights changed — the one unavoidable update.
            self._bar_item.setOpts(height=heights)

    def _refresh_levels(self, view: Any, values: dict[str, Any]) -> None:
        levels = getattr(view, "levels", ())
        while len(self._level_items) < len(levels):
            line = pg.InfiniteLine(angle=0, movable=False)
            self.addItem(line, ignoreBounds=True)
            self._level_items.append(line)
        for index, line in enumerate(self._level_items):
            if index >= len(levels):
                if line.isVisible():
                    line.hide()
                continue
            marker = levels[index]
            value = resolve_binding(marker.value, values)
            if value is None:
                if line.isVisible():
                    line.hide()
                continue
            sig = (marker.orientation, marker.color, float(marker.width))
            if self._level_sigs.get(index) != sig:
                line.setAngle(0.0 if marker.orientation == "horizontal" else 90.0)
                line.setPen(pg.mkPen(marker.color, width=float(marker.width)))
                self._level_sigs[index] = sig
            if line.value() != float(value):
                line.setValue(float(value))
            if not line.isVisible():
                line.show()

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

    def _apply_background(self, view: LinePlotViewSpec, values: dict[str, Any]) -> None:
        background = resolve_binding(view.background_color, values)
        if background is not None and background != self._cache_background:
            self.setBackground(background)
            self._cache_background = background

    def _resolved_view_title(self, view: LinePlotViewSpec, values: dict[str, Any], fallback: str) -> str:
        title = resolve_binding(view.title, values)
        if title is None or title == "":
            return str(fallback)
        return str(title)

    def _select_field_for_view(
        self,
        view: LinePlotViewSpec,
        field: Field,
        values: dict[str, Any],
    ) -> Field | None:
        resolved_selectors = {}
        for dim, selector in view.selectors.items():
            resolved = resolve_binding(selector, values)
            if resolved is None:
                self._plot_item.setData([], [])
                return None
            filtered = self._filter_selector_for_field(field, dim, resolved)
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

    def _filter_selector_for_field(self, field: Field, dim: str, selector: Any) -> Any | None:
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
            return filtered or None
        return selector

    def _refresh_single_trace(
        self,
        view: LinePlotViewSpec,
        field: Field,
        x_dim: str,
        values: dict[str, Any],
        *,
        source_field_id: str,
    ) -> None:
        self._clear_series()
        if len(field.dims) != 1 or field.dims[0] != x_dim:
            raise ValueError(f"LinePlotViewSpec '{view.id}' must resolve to a 1D field along '{x_dim}'")

        x = np.asarray(field.coord(x_dim), dtype=np.float32)
        y = np.asarray(field.values, dtype=np.float32)
        x, y = self._trim_line_data(view, x, y)
        title = self._resolved_view_title(view, values, source_field_id)
        structural_sig = (
            "single", view.id, view.x_label or x_dim, view.x_unit,
            view.y_label, view.y_unit, title,
        )
        self._apply_single_trace_structure(
            structural_sig,
            x_label=view.x_label or x_dim,
            x_unit=view.x_unit,
            y_label=view.y_label,
            y_unit=view.y_unit,
            title=title,
        )
        self._apply_single_pen(resolve_binding(view.pen, values))
        self._plot_item.setData(x, y)
        self._apply_view_ranges(view, x)

    def _apply_single_trace_structure(
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

    def _apply_single_pen(self, resolved_color) -> None:
        cached_pen = self._cache_pens.get("__single__")
        if cached_pen is None or cached_pen[0] != resolved_color:
            pen = pg.mkPen(resolved_color, width=2)
            self._cache_pens["__single__"] = (resolved_color, pen)
            self._plot_item.setPen(pen)

    def _refresh_series(self, view: LinePlotViewSpec, field: Field, x_dim: str, values: dict[str, Any]) -> None:
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
        view: LinePlotViewSpec,
        field: Field,
        x_dim: str,
        series_dim: str,
    ) -> tuple[np.ndarray, np.ndarray, list[str]]:
        if set(field.dims) != {series_dim, x_dim} or field.values.ndim != 2:
            raise ValueError(
                f"LinePlotViewSpec '{view.id}' with series_dim='{series_dim}' must resolve to a 2D field over ({series_dim}, {x_dim})"
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
        view: LinePlotViewSpec,
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
        view: LinePlotViewSpec,
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

    def _series_pen(self, view: LinePlotViewSpec, label: str, idx: int, values: dict[str, Any]):
        color = self._series_color(view, label, idx)
        resolved_color = resolve_binding(color, values)
        cached = self._cache_pens.get(label)
        if cached is not None and cached[0] == resolved_color:
            return cached[1], False
        pen = pg.mkPen(resolved_color, width=2)
        self._cache_pens[label] = (resolved_color, pen)
        return pen, True

    def _series_color(self, view: LinePlotViewSpec, label: str, idx: int):
        if label in view.series_colors:
            return view.series_colors[label]
        if view.series_palette:
            return view.series_palette[idx % len(view.series_palette)]
        return view.pen

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

    def _trim_line_data(self, view: LinePlotViewSpec, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if not view.trim_to_rolling_window or view.rolling_window is None or len(x) == 0:
            return self._finite_line_data(x, y)
        mask = self._rolling_window_mask(x, float(view.rolling_window))
        return self._finite_line_data(x[mask], y[mask])

    def _trim_series_data(
        self,
        view: LinePlotViewSpec,
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

    def _apply_view_ranges(self, view: LinePlotViewSpec, x: np.ndarray) -> None:
        self._apply_y_range(view)
        xmin, xmax = self._apply_x_range(view, x)
        self._apply_tick_spacing(view, xmin, xmax)

    def _apply_y_range(self, view: LinePlotViewSpec) -> None:
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

    def _apply_x_range(self, view: LinePlotViewSpec, x: np.ndarray) -> tuple[float, float]:
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

    def _apply_tick_spacing(self, view: LinePlotViewSpec, xmin: float, xmax: float) -> None:
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


class LinePlotHostPanel(QtWidgets.QGroupBox):
    def __init__(
        self,
        *,
        panel_id: str,
        view_id: str,
        title: str | None = None,
        show_internal_title: bool = True,
        parent=None,
    ):
        host_title = str(title) if title else None
        super().__init__(host_title or "", parent)
        self._host_title = host_title
        self.panel_id = panel_id
        self.view_id = view_id
        self.line_plot_panel = LinePlotPanel(
            show_internal_title=show_internal_title,
            perf_panel_id=panel_id,
            perf_view_id=view_id,
        )
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.addWidget(self.line_plot_panel)

    def refresh(
        self,
        view: LinePlotViewSpec | None,
        field: Field | None,
        values: dict[str, Any],
    ) -> None:
        started = time.monotonic()
        self.line_plot_panel.refresh(view, field, values)
        if view is None:
            self.setTitle(self._host_title or "")
            return
        self.setTitle(self._host_title or "")
        duration_ms = round((time.monotonic() - started) * 1000.0, 3)
        if duration_ms >= 5.0:
            perf_log(
                "line_plot",
                "refresh",
                panel_id=self.panel_id,
                view_id=self.view_id,
                field_id=getattr(view, "field_id", None),
                duration_ms=duration_ms,
                field_shape=getattr(getattr(field, "values", None), "shape", None),
                panel_width_px=self.line_plot_panel.width(),
                panel_height_px=self.line_plot_panel.height(),
            )
