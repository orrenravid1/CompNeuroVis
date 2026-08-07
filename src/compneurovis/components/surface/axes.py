from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from vispy import scene
from vispy.color import Color


# Only used until set_axes_style() applies the view's sizes; kept in step with
# SurfaceRenderConfig's defaults so axes never flash at the wrong size.
DEFAULT_TICK_LABEL_SIZE = 30.0
DEFAULT_AXIS_LABEL_SIZE = 50.0

# How far an axis label sits past its tick labels, as a multiple of the tick-label
# offset. Text is sized in screen space while these offsets are in world space, so
# this is a clearance heuristic: raise it if labels crowd the tick values.
AXIS_LABEL_CLEARANCE = 3.6

_TICK_ANCHORS = {
    "x": ("center", "top"),
    "y": ("right", "center"),
    "z": ("left", "center"),
}

_AXIS_LABEL_ANCHORS = {
    "x": ("center", "top"),
    "y": ("right", "center"),
    "z": ("left", "center"),
}


class SurfaceAxesOverlay:
    def __init__(self, view):
        self.view = view
        self._axis_lines = None
        self._tick_lines = None
        self._tick_labels: dict[str, scene.visuals.Text] = {}
        self._axis_labels: dict[str, scene.visuals.Text] = {}

    def clear(self) -> None:
        visuals = [
            self._axis_lines,
            self._tick_lines,
            *self._tick_labels.values(),
            *self._axis_labels.values(),
        ]
        for vis in visuals:
            if vis is None:
                continue
            vis.parent = None
        self._axis_lines = None
        self._tick_lines = None
        self._tick_labels.clear()
        self._axis_labels.clear()

    def set_axes_geometry(
        self,
        *,
        render_axes,
        axes_in_middle,
        tick_count,
        tick_length_scale,
        axis_labels,
        x,
        y,
        z,
        tick_value_scales=(1.0, 1.0, 1.0),
    ) -> None:
        if not render_axes:
            self._set_visible(False)
            return

        self._set_visible(True)
        geometry = _build_axes_overlay_geometry(
            axes_in_middle=bool(axes_in_middle),
            tick_count=max(0, int(tick_count)),
            tick_length_scale=float(tick_length_scale),
            axis_labels=axis_labels,
            x=x,
            y=y,
            z=z,
            tick_value_scales=tick_value_scales,
        )
        self._update_axis_lines(geometry.axis_segments)
        self._update_tick_lines(geometry.tick_segments)
        self._update_tick_labels(geometry.tick_labels)
        self._update_axis_labels(geometry.axis_labels)

    def set_axes_style(
        self,
        *,
        render_axes,
        tick_label_size,
        axis_label_size,
        axis_color,
        text_color,
        axis_alpha,
    ) -> None:
        if not render_axes:
            self._set_visible(False)
            return

        axis_rgba = _with_alpha(axis_color, axis_alpha)
        text_rgba = _with_alpha(text_color, axis_alpha)

        if self._axis_lines is not None:
            self._axis_lines.set_data(color=axis_rgba, width=2.0)
        if self._tick_lines is not None:
            self._tick_lines.set_data(color=axis_rgba, width=1.0)
        for visual in self._tick_labels.values():
            visual.color = text_rgba
            visual.font_size = tick_label_size
        for visual in self._axis_labels.values():
            visual.color = text_rgba
            visual.font_size = axis_label_size

    def _update_axis_lines(self, segments: np.ndarray) -> None:
        axis_visual = self._ensure_line_visual(attr_name="_axis_lines", width=2.0)
        axis_visual.set_data(pos=segments, connect="segments")
        axis_visual.visible = True

    def _update_tick_lines(self, segments: np.ndarray) -> None:
        tick_visual = self._ensure_line_visual(attr_name="_tick_lines", width=1.0)
        if segments.size:
            tick_visual.set_data(pos=segments, connect="segments")
            tick_visual.visible = True
        else:
            tick_visual.visible = False

    def _update_tick_labels(self, labels: dict[str, _TextBatch]) -> None:
        for axis_name, batch in labels.items():
            self._update_text_visual(
                self._ensure_tick_label_visual(axis_name),
                texts=batch.texts,
                positions=batch.positions,
            )

    def _update_axis_labels(self, labels: dict[str, _TextBatch]) -> None:
        for axis_name, batch in labels.items():
            visual = self._ensure_axis_label_visual(axis_name)
            if not batch.texts:
                visual.text = ""
                visual.visible = False
                continue
            visual.text = batch.texts[0]
            visual.pos = np.asarray(batch.positions, dtype=np.float32)
            visual.visible = True

    def _ensure_line_visual(self, *, attr_name: str, width: float):
        visual = getattr(self, attr_name)
        if visual is not None:
            return visual
        visual = scene.visuals.Line(
            pos=np.zeros((2, 3), dtype=np.float32),
            color=(0.0, 0.0, 0.0, 1.0),
            width=width,
            connect="segments",
            method="gl",
            parent=self.view.scene,
        )
        visual.set_gl_state(depth_test=False, blend=True)
        visual.order = 1000
        setattr(self, attr_name, visual)
        return visual

    def _ensure_tick_label_visual(self, axis_name: str):
        visual = self._tick_labels.get(axis_name)
        if visual is not None:
            return visual
        anchor_x, anchor_y = _TICK_ANCHORS[axis_name]
        visual = scene.visuals.Text(
            text=[],
            pos=np.zeros((1, 3), dtype=np.float32),
            color="black",
            font_size=DEFAULT_TICK_LABEL_SIZE,
            anchor_x=anchor_x,
            anchor_y=anchor_y,
            parent=self.view.scene,
        )
        visual.set_gl_state(depth_test=False, blend=True)
        visual.order = 1000
        self._tick_labels[axis_name] = visual
        return visual

    def _ensure_axis_label_visual(self, axis_name: str):
        visual = self._axis_labels.get(axis_name)
        if visual is not None:
            return visual
        anchor_x, anchor_y = _AXIS_LABEL_ANCHORS[axis_name]
        visual = scene.visuals.Text(
            text="",
            pos=np.zeros((1, 3), dtype=np.float32),
            color="black",
            font_size=DEFAULT_AXIS_LABEL_SIZE,
            bold=True,
            anchor_x=anchor_x,
            anchor_y=anchor_y,
            parent=self.view.scene,
        )
        visual.set_gl_state(depth_test=False, blend=True)
        visual.order = 1000
        self._axis_labels[axis_name] = visual
        return visual

    def _set_visible(self, visible: bool) -> None:
        visuals = [
            self._axis_lines,
            self._tick_lines,
            *self._tick_labels.values(),
            *self._axis_labels.values(),
        ]
        for visual in visuals:
            if visual is not None:
                visual.visible = visible

    def _update_text_visual(self, visual, *, texts, positions) -> None:
        if not texts:
            visual.text = []
            visual.visible = False
            return
        visual.text = texts
        visual.pos = np.asarray(positions, dtype=np.float32)
        visual.visible = True


@dataclass(slots=True)
class _AxesBounds:
    xmin: float
    xmax: float
    ymin: float
    ymax: float
    zmin: float
    zmax: float

    @property
    def xmid(self) -> float:
        return 0.5 * (self.xmin + self.xmax)

    @property
    def ymid(self) -> float:
        return 0.5 * (self.ymin + self.ymax)

    @property
    def zmid(self) -> float:
        return 0.5 * (self.zmin + self.zmax)


@dataclass(slots=True)
class _AxesOrigin:
    x: float
    y: float
    z: float


@dataclass(slots=True)
class _AxesOffsets:
    xtick: float
    ytick: float
    ztick: float
    x_tick_label: float
    y_tick_label: float
    z_tick_label: float
    x_axis_label: float
    y_axis_label: float
    z_axis_label: float


@dataclass(slots=True)
class _TextBatch:
    texts: list[str]
    positions: list[list[float]]


@dataclass(slots=True)
class _AxesOverlayGeometry:
    axis_segments: np.ndarray
    tick_segments: np.ndarray
    tick_labels: dict[str, _TextBatch]
    axis_labels: dict[str, _TextBatch]


def _build_axes_overlay_geometry(
    *,
    axes_in_middle: bool,
    tick_count: int,
    tick_length_scale: float,
    axis_labels,
    x,
    y,
    z,
    tick_value_scales=(1.0, 1.0, 1.0),
) -> _AxesOverlayGeometry:
    bounds = _axes_bounds(x, y, z)
    origin = _axes_origin(bounds, axes_in_middle=axes_in_middle)
    offsets = _axes_offsets(bounds, tick_length_scale=tick_length_scale)
    tick_segments, tick_labels = _tick_geometry(
        bounds, origin, offsets, tick_count, tick_value_scales
    )
    return _AxesOverlayGeometry(
        axis_segments=_axis_segments(bounds, origin),
        tick_segments=tick_segments,
        tick_labels=tick_labels,
        axis_labels=_axis_label_geometry(bounds, origin, offsets, axis_labels),
    )


def _axes_bounds(x, y, z) -> _AxesBounds:
    return _AxesBounds(
        xmin=float(np.min(x)),
        xmax=float(np.max(x)),
        ymin=float(np.min(y)),
        ymax=float(np.max(y)),
        zmin=float(np.min(z)),
        zmax=float(np.max(z)),
    )


def _axes_origin(bounds: _AxesBounds, *, axes_in_middle: bool) -> _AxesOrigin:
    return _AxesOrigin(
        x=bounds.xmid if axes_in_middle else bounds.xmin,
        y=bounds.ymid if axes_in_middle else bounds.ymin,
        z=bounds.zmid if axes_in_middle else bounds.zmin,
    )


def _axes_offsets(bounds: _AxesBounds, *, tick_length_scale: float) -> _AxesOffsets:
    x_span = max(bounds.xmax - bounds.xmin, 1e-6)
    y_span = max(bounds.ymax - bounds.ymin, 1e-6)
    x_tick_label = 0.09 * y_span
    y_tick_label = 0.07 * x_span
    z_tick_label = 0.07 * x_span
    return _AxesOffsets(
        xtick=0.03 * y_span * tick_length_scale,
        ytick=0.03 * x_span * tick_length_scale,
        ztick=0.03 * x_span * tick_length_scale,
        x_tick_label=x_tick_label,
        y_tick_label=y_tick_label,
        z_tick_label=z_tick_label,
        x_axis_label=AXIS_LABEL_CLEARANCE * x_tick_label,
        y_axis_label=AXIS_LABEL_CLEARANCE * y_tick_label,
        z_axis_label=AXIS_LABEL_CLEARANCE * z_tick_label,
    )


def _axis_segments(bounds: _AxesBounds, origin: _AxesOrigin) -> np.ndarray:
    return np.asarray(
        [
            [bounds.xmin, origin.y, origin.z],
            [bounds.xmax, origin.y, origin.z],
            [origin.x, bounds.ymin, origin.z],
            [origin.x, bounds.ymax, origin.z],
            [origin.x, origin.y, bounds.zmin],
            [origin.x, origin.y, bounds.zmax],
        ],
        dtype=np.float32,
    )


def _tick_geometry(
    bounds: _AxesBounds,
    origin: _AxesOrigin,
    offsets: _AxesOffsets,
    tick_count: int,
    tick_value_scales,
) -> tuple[np.ndarray, dict[str, _TextBatch]]:
    tick_segments: list[list[float]] = []
    labels = {
        "x": _TextBatch(texts=[], positions=[]),
        "y": _TextBatch(texts=[], positions=[]),
        "z": _TextBatch(texts=[], positions=[]),
    }

    if tick_count <= 0:
        return np.zeros((0, 3), dtype=np.float32), labels

    scales = tuple(float(item) for item in tick_value_scales)
    if len(scales) != 3 or not all(
        np.isfinite(item) and item > 0 for item in scales
    ):
        raise ValueError(
            "Surface tick_value_scales must contain three positive finite values"
        )
    x_scale, y_scale, z_scale = scales

    for xv in np.linspace(bounds.xmin, bounds.xmax, tick_count):
        tick_segments.extend([[xv, origin.y - offsets.xtick, origin.z], [xv, origin.y + offsets.xtick, origin.z]])
        labels["x"].texts.append(
            _format_tick_value(
                float(xv) / x_scale,
                bounds.xmin / x_scale,
                bounds.xmax / x_scale,
                tick_count,
            )
        )
        labels["x"].positions.append([xv, origin.y - offsets.x_tick_label, origin.z])

    for yv in np.linspace(bounds.ymin, bounds.ymax, tick_count):
        tick_segments.extend([[origin.x - offsets.ytick, yv, origin.z], [origin.x + offsets.ytick, yv, origin.z]])
        labels["y"].texts.append(
            _format_tick_value(
                float(yv) / y_scale,
                bounds.ymin / y_scale,
                bounds.ymax / y_scale,
                tick_count,
            )
        )
        labels["y"].positions.append([origin.x - offsets.y_tick_label, yv, origin.z])

    for zv in np.linspace(bounds.zmin, bounds.zmax, tick_count):
        tick_segments.extend([[origin.x - offsets.ztick, origin.y, zv], [origin.x + offsets.ztick, origin.y, zv]])
        labels["z"].texts.append(
            _format_tick_value(
                float(zv) / z_scale,
                bounds.zmin / z_scale,
                bounds.zmax / z_scale,
                tick_count,
            )
        )
        labels["z"].positions.append([origin.x + offsets.z_tick_label, origin.y, zv])

    return np.asarray(tick_segments, dtype=np.float32), labels


def _axis_label_geometry(
    bounds: _AxesBounds,
    origin: _AxesOrigin,
    offsets: _AxesOffsets,
    axis_labels,
) -> dict[str, _TextBatch]:
    specs = {
        "x": (str(axis_labels[0]), [[bounds.xmax, origin.y - offsets.x_axis_label, origin.z]]),
        "y": (str(axis_labels[1]), [[origin.x - offsets.y_axis_label, bounds.ymax, origin.z]]),
        "z": (str(axis_labels[2]), [[origin.x + offsets.z_axis_label, origin.y, bounds.zmax]]),
    }
    return {
        axis_name: _TextBatch(texts=[text] if text else [], positions=position)
        for axis_name, (text, position) in specs.items()
    }


def _format_tick_value(value: float, lo: float, hi: float, tick_count: int) -> str:
    span = abs(float(hi) - float(lo))
    if span < 1e-12:
        return f"{value:.3g}"
    step = span / max(1.0, float(max(1, tick_count - 1)))
    decimals = 0
    rounded = round(step)
    if abs(step - rounded) > 1e-9:
        decimals = min(6, max(1, int(math.ceil(-math.log10(abs(step - rounded)))) + 1))
    elif step < 1.0:
        decimals = min(6, max(0, int(math.ceil(-math.log10(step)))))
    text = f"{value:.{decimals}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _with_alpha(color, alpha: float):
    rgba = list(Color(color).rgba)
    rgba[3] = min(1.0, max(0.0, float(alpha)))
    return tuple(rgba)
