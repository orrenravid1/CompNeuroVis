from __future__ import annotations

import time

import numpy as np
from PyQt6 import QtWidgets

from dataclasses import dataclass
from typing import Any

from compneurovis.core._perf import perf_log
from compneurovis.core.field import Field
from compneurovis.core.views import StateGraphViewSpec
from compneurovis.frontends.vispy.renderers.colormaps import _colormap_samples
from compneurovis.frontends.vispy.view_inputs.bindings import resolve_binding


_LABEL_LUM_WEIGHTS = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
_MARKER_EDGE_COLOR = np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32)


@dataclass(frozen=True, slots=True)
class _ResolvedStyle:
    """View style with every binding resolved against the current values."""

    node_size: float
    edge_width: float
    arrow_size: float
    label_size: float
    label_offset_x: float
    label_offset_y: float
    node_color_map: str
    edge_color_map: str
    background_color: Any


def _resolve_style(view: "StateGraphViewSpec", values: dict) -> _ResolvedStyle:
    def num(prop, fallback):
        resolved = resolve_binding(getattr(view, prop), values)
        return float(fallback if resolved is None else resolved)

    background = resolve_binding(view.background_color, values)
    return _ResolvedStyle(
        node_size=num("node_size", 20.0),
        edge_width=num("edge_width", 4.0),
        arrow_size=num("arrow_size", 18.0),
        label_size=num("label_size", 10.0),
        label_offset_x=num("label_offset_x", 0.0),
        label_offset_y=num("label_offset_y", 0.0),
        node_color_map=str(resolve_binding(view.node_color_map, values) or "fire"),
        edge_color_map=str(resolve_binding(view.edge_color_map, values) or "bwr"),
        background_color="white" if background is None else background,
    )


def _state_label_color_for_fill(rgba: np.ndarray) -> tuple[float, float, float, float]:
    luminance = float(np.dot(rgba[:3].astype(np.float32), _LABEL_LUM_WEIGHTS))
    return (1.0, 1.0, 1.0, 1.0) if luminance < 0.45 else (0.0, 0.0, 0.0, 1.0)


def _state_node_colormap_name(cmap_name: str) -> str:
    return "state-fire" if str(cmap_name).strip().lower() == "fire" else cmap_name


class StateGraphPanel(QtWidgets.QWidget):
    """VisPy canvas panel rendering a live-colored state-transition graph."""

    def __init__(self, parent=None, *, perf_panel_id: str | None = None, perf_view_id: str | None = None):
        super().__init__(parent)
        self._perf_panel_id = perf_panel_id
        self._perf_view_id = perf_view_id
        from vispy import scene as vscene
        self._vscene = vscene
        self._canvas = vscene.SceneCanvas(keys="interactive", bgcolor="white", show=False)
        self._view = self._canvas.central_widget.add_view()
        self._view.camera = vscene.cameras.PanZoomCamera(aspect=1)
        self._view.camera.set_range(x=(-0.15, 1.15), y=(-0.15, 1.15))
        self._markers = None
        self._edge_visual = None
        self._label_visual = None
        self._node_order: list[str] = []
        self._edge_order: list[str] = []
        self._node_pos: np.ndarray | None = None
        self._edge_pos: np.ndarray | None = None
        self._arrow_data: np.ndarray | None = None
        self._node_color_buf: np.ndarray | None = None
        self._label_color_buf: np.ndarray | None = None
        self._edge_color_buf: np.ndarray | None = None
        self._edge_segment_color_buf: np.ndarray | None = None
        self._field_index_cache: dict[tuple[str, tuple[str, ...], tuple[str, ...]], np.ndarray] = {}
        self._spec_sig: tuple | None = None
        lo = QtWidgets.QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.addWidget(self._canvas.native)

    def refresh(
        self,
        view: "StateGraphViewSpec",
        node_field: "Field | None",
        edge_field: "Field | None",
        values: dict | None = None,
    ) -> None:
        started = time.monotonic()
        style = _resolve_style(view, {} if values is None else values)
        sig = (view.node_positions, view.edges, style.node_size, style.background_color,
               style.node_color_map, style.edge_color_map, style.edge_width,
               style.arrow_size, style.label_size)
        if sig != self._spec_sig or self._markers is None:
            self._build_visuals(view, style)
            self._spec_sig = sig

        n = len(self._node_order)
        if n == 0:
            return

        self._position_labels(style)

        if node_field is not None:
            nv = self._read_field_values(node_field, self._node_order, "state")
            nc = self._apply_cmap(nv, _state_node_colormap_name(style.node_color_map), view.node_color_limits)
            if self._node_color_buf is None or self._node_color_buf.shape != nc.shape:
                self._node_color_buf = np.empty_like(nc)
            self._node_color_buf[:, :] = nc
        else:
            if self._node_color_buf is None or self._node_color_buf.shape != (n, 4):
                self._node_color_buf = np.empty((n, 4), dtype=np.float32)
            self._node_color_buf[:, :] = [0.5, 0.5, 0.5, 1.0]
        self._markers.set_data(
            pos=self._node_pos, face_color=self._node_color_buf,
            size=style.node_size, edge_color=_MARKER_EDGE_COLOR, edge_width=1.5,
        )
        if self._label_visual is not None and self._label_color_buf is not None:
            lums = self._node_color_buf[:, :3] @ _LABEL_LUM_WEIGHTS
            self._label_color_buf[:, :3] = (lums < 0.45)[:, np.newaxis]
            self._label_visual.color = self._label_color_buf

        n_edges = len(view.edges)
        if self._edge_visual is not None and n_edges > 0:
            self._position_edges(view, style)
            if edge_field is not None:
                ev = self._read_field_values(edge_field, self._edge_order, "edge")
                ec = self._apply_cmap(ev, style.edge_color_map, view.edge_color_limits)
                if self._edge_color_buf is None or self._edge_color_buf.shape != ec.shape:
                    self._edge_color_buf = np.empty_like(ec)
                self._edge_color_buf[:, :] = ec
            else:
                if self._edge_color_buf is None or self._edge_color_buf.shape != (n_edges, 4):
                    self._edge_color_buf = np.empty((n_edges, 4), dtype=np.float32)
                self._edge_color_buf[:, :] = [0.55, 0.55, 0.55, 0.85]
            if self._edge_segment_color_buf is None or self._edge_segment_color_buf.shape != (n_edges * 2, 4):
                self._edge_segment_color_buf = np.empty((n_edges * 2, 4), dtype=np.float32)
            self._edge_segment_color_buf[0::2, :] = self._edge_color_buf
            self._edge_segment_color_buf[1::2, :] = self._edge_color_buf
            self._edge_visual.set_data(color=self._edge_segment_color_buf)
            # Heads carry the same flux color as their stroke, not vispy's default grey.
            self._edge_visual.arrow_color = self._edge_color_buf

        self._canvas.update()
        duration_ms = round((time.monotonic() - started) * 1000.0, 3)
        if duration_ms >= 5.0:
            perf_log(
                "state_graph", "refresh",
                panel_id=self._perf_panel_id,
                view_id=self._perf_view_id,
                duration_ms=duration_ms,
            )

    def paintEvent(self, event) -> None:
        started = time.monotonic()
        super().paintEvent(event)
        duration_ms = round((time.monotonic() - started) * 1000.0, 3)
        if duration_ms >= 5.0:
            perf_log(
                "state_graph", "paint",
                panel_id=self._perf_panel_id,
                view_id=self._perf_view_id,
                duration_ms=duration_ms,
            )

    def _px_per_data(self) -> np.ndarray:
        """Scene scale, per axis. Markers, glyphs and strokes are all sized in pixels."""
        transform = self._view.scene.node_transform(self._canvas.scene)
        origin = np.asarray(transform.map([0.0, 0.0])[:2], dtype=np.float64)
        unit = np.asarray(transform.map([1.0, 1.0])[:2], dtype=np.float64)
        scale = np.abs(unit - origin)
        scale[scale < 1e-9] = 1.0
        return scale

    def _position_labels(self, style: _ResolvedStyle) -> None:
        """Place labels at the node centres, nudged by the offsets (given in pixels).

        The offsets are pixels because the glyphs and the node markers are both
        sized in pixels, so a data-space nudge would drift with zoom. Convert
        through the current scene transform instead.
        """
        if self._label_visual is None or self._node_pos is None:
            return
        pos = self._node_pos
        if style.label_offset_x or style.label_offset_y:
            px_per_data = self._px_per_data()
            pos = pos + np.asarray(
                [style.label_offset_x / px_per_data[0], style.label_offset_y / px_per_data[1]],
                dtype=np.float32,
            )
        self._label_visual.pos = pos

    def _edge_geometry(self, view: "StateGraphViewSpec", style: _ResolvedStyle) -> tuple[np.ndarray, np.ndarray]:
        """Segment endpoints and arrow anchors, trimmed clear of the node discs.

        The node radius and the stroke width are pixel quantities, so the gap has
        to be converted into data units against the current scene scale -- a fixed
        data-space gap would tuck the arrowheads under any sufficiently large node.
        """
        node_dict = self._node_dict(view)
        scale = float(self._px_per_data().mean())
        node_gap = (0.5 * style.node_size + 2.0) / scale
        parallel_gap = (style.edge_width + 5.0) / scale
        edge_set = {(src, tgt) for src, tgt, _ in view.edges}

        line_segs: list[tuple[float, float]] = []
        arrow_pts: list[list[float]] = []
        for src, tgt, _ in view.edges:
            sx, sy = node_dict[src]
            tx, ty = node_dict[tgt]
            dx, dy = tx - sx, ty - sy
            length = max(float(np.sqrt(dx * dx + dy * dy)), 1e-9)
            ux, uy = dx / length, dy / length
            px, py = -dy / length, dx / length
            ox, oy = (px * parallel_gap, py * parallel_gap) if (tgt, src) in edge_set else (0.0, 0.0)
            gap = min(node_gap, 0.45 * length)
            x0, y0 = sx + ox + ux * gap, sy + oy + uy * gap
            x1, y1 = tx + ox - ux * gap, ty + oy - uy * gap
            line_segs.extend([(x0, y0), (x1, y1)])
            arrow_pts.append([x0, y0, x1, y1])
        return np.array(line_segs, dtype=np.float32), np.array(arrow_pts, dtype=np.float32)

    def _position_edges(self, view: "StateGraphViewSpec", style: _ResolvedStyle) -> None:
        if self._edge_visual is None or not view.edges:
            return
        pos, arrows = self._edge_geometry(view, style)
        if self._edge_pos is not None and np.array_equal(pos, self._edge_pos):
            return
        self._edge_pos, self._arrow_data = pos, arrows
        # `arrows` and `width` are read-only on the visual; set_data is the only way in.
        self._edge_visual.set_data(pos=pos, arrows=arrows, width=style.edge_width)

    def _build_visuals(self, view: "StateGraphViewSpec", style: _ResolvedStyle) -> None:
        vscene = self._vscene
        if self._label_visual is not None:
            self._label_visual.parent = None
            self._label_visual = None
        self._label_color_buf = None
        if self._markers is not None:
            self._markers.parent = None
            self._markers = None
        if self._edge_visual is not None:
            self._edge_visual.parent = None
            self._edge_visual = None

        self._canvas.bgcolor = style.background_color
        self._field_index_cache.clear()
        node_dict = self._node_dict(view)
        self._node_order = [name for name, x, y in view.node_positions]
        self._edge_order = [eid for src, tgt, eid in view.edges]
        n = len(self._node_order)
        if n == 0:
            self._node_pos = None
            self._node_color_buf = None
            self._edge_color_buf = None
            self._edge_segment_color_buf = None
            return

        self._node_pos = np.array(
            [[node_dict[nm][0], node_dict[nm][1]] for nm in self._node_order], dtype=np.float32
        )
        self._node_color_buf = np.full((n, 4), [0.5, 0.5, 0.5, 1.0], dtype=np.float32)
        self._markers = vscene.visuals.Markers(parent=self._view.scene)
        self._markers.set_data(
            pos=self._node_pos, face_color=self._node_color_buf,
            size=style.node_size, edge_color=_MARKER_EDGE_COLOR, edge_width=1.5,
        )
        self._label_color_buf = np.zeros((n, 4), dtype=np.float32)
        self._label_color_buf[:, 3] = 1.0
        self._label_visual = vscene.visuals.Text(
            text=[str(nm) for nm in self._node_order],
            pos=self._node_pos,
            color=self._label_color_buf,
            font_size=style.label_size,
            bold=True,
            anchor_x="center",
            anchor_y="center",
            parent=self._view.scene,
        )

        n_edges = len(view.edges)
        if n_edges == 0:
            return

        self._edge_pos, self._arrow_data = self._edge_geometry(view, style)
        self._edge_color_buf = np.full((n_edges, 4), [0.55, 0.55, 0.55, 0.85], dtype=np.float32)
        self._edge_segment_color_buf = np.repeat(self._edge_color_buf, 2, axis=0)
        self._edge_visual = vscene.visuals.Arrow(
            pos=self._edge_pos,
            connect="segments",
            color=self._edge_segment_color_buf,
            width=style.edge_width,
            arrows=self._arrow_data,
            arrow_size=style.arrow_size,
            arrow_type="stealth",
            arrow_color=self._edge_color_buf,
            parent=self._view.scene,
        )

    def _node_dict(self, view: "StateGraphViewSpec") -> dict[str, tuple[float, float]]:
        return {name: (float(x), float(y)) for name, x, y in view.node_positions}

    def _read_field_values(self, field: "Field", names: list[str], dim: str) -> np.ndarray:
        data_dim = dim if dim in field.dims else field.dims[0]
        coord_key = tuple(str(s) for s in field.coord(data_dim).tolist())
        name_key = tuple(names)
        cache_key = (data_dim, coord_key, name_key)
        idx = self._field_index_cache.get(cache_key)
        if idx is None:
            idx_map = {nm: i for i, nm in enumerate(coord_key)}
            idx = np.array([idx_map.get(nm, -1) for nm in name_key], dtype=np.int32)
            self._field_index_cache[cache_key] = idx

        source = np.asarray(field.values, dtype=np.float32)
        out = np.zeros(len(idx), dtype=np.float32)
        valid = idx >= 0
        if np.any(valid):
            out[valid] = source[idx[valid]]
        return out

    def _apply_cmap(self, values: np.ndarray, cmap_name: str, limits: tuple[float, float]) -> np.ndarray:
        values = np.asarray(values, dtype=np.float32)
        vmin, vmax = float(limits[0]), float(limits[1])
        if vmax > vmin:
            norm = np.clip((values - vmin) / (vmax - vmin), 0.0, 1.0)
        else:
            norm = np.zeros(len(values), dtype=np.float32)
        try:
            lut = _colormap_samples(cmap_name)
        except (KeyError, ValueError):
            lut = _colormap_samples("grays")
        idx = np.clip((norm * (len(lut) - 1)).astype(np.int32), 0, len(lut) - 1)
        return lut[idx].astype(np.float32, copy=False)


