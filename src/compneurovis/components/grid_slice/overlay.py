from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from vispy import scene
from vispy.color import Color


class SurfaceSliceOverlay:
    def __init__(self, view):
        self.view = view
        self._line = None
        self._fill = None

    def clear(self):
        if self._line is not None:
            self._line.parent = None
            self._line = None
        self._remove_fill()

    def set_slice(self, *, axis, value, color, alpha, fill_alpha, width, x, y, z):
        geometry = _slice_overlay_geometry(axis=axis, value=value, x=x, y=y, z=z)
        line_rgba = _with_alpha(color, alpha)
        fill_rgba = _with_alpha(color, fill_alpha)

        self._update_fill(geometry, fill_rgba)
        self._update_line(geometry, line_rgba, width)

    def _update_fill(self, geometry: _SliceOverlayGeometry, fill_rgba) -> None:
        if fill_rgba[3] <= 0.0:
            self._remove_fill()
            return
        if self._fill is None:
            self._fill = scene.visuals.Mesh(
                vertices=geometry.fill_vertices,
                faces=geometry.fill_faces,
                color=fill_rgba,
                shading=None,
                parent=self.view.scene,
            )
            self._fill.set_gl_state(depth_test=False, blend=True, cull_face=False)
            self._fill.order = 999
        else:
            self._fill.set_data(vertices=geometry.fill_vertices, faces=geometry.fill_faces, color=fill_rgba)

    def _remove_fill(self) -> None:
        if self._fill is not None:
            self._fill.parent = None
            self._fill = None

    def _update_line(self, geometry: _SliceOverlayGeometry, line_rgba, width) -> None:
        if self._line is None:
            self._line = scene.visuals.Line(
                pos=geometry.line_vertices,
                color=line_rgba,
                width=float(width),
                method="gl",
                parent=self.view.scene,
            )
            self._line.set_gl_state(depth_test=False, blend=True)
            self._line.order = 1000
        else:
            self._line.set_data(pos=geometry.line_vertices, color=line_rgba, width=float(width))


@dataclass(slots=True)
class _SliceOverlayGeometry:
    line_vertices: np.ndarray
    fill_vertices: np.ndarray
    fill_faces: np.ndarray


def _slice_overlay_geometry(*, axis, value, x, y, z) -> _SliceOverlayGeometry:
    xmin, xmax = float(np.min(x)), float(np.max(x))
    ymin, ymax = float(np.min(y)), float(np.max(y))
    zmin, zmax = float(np.min(z)), float(np.max(z))

    if axis == "y":
        value = min(max(float(value), ymin), ymax)
        line_vertices = np.array(
            [
                [xmin, value, zmin],
                [xmax, value, zmin],
                [xmax, value, zmax],
                [xmin, value, zmax],
                [xmin, value, zmin],
            ],
            dtype=np.float32,
        )
        fill_vertices = np.array(
            [
                [xmin, value, zmin],
                [xmax, value, zmin],
                [xmax, value, zmax],
                [xmin, value, zmax],
            ],
            dtype=np.float32,
        )
    else:
        value = min(max(float(value), xmin), xmax)
        line_vertices = np.array(
            [
                [value, ymin, zmin],
                [value, ymax, zmin],
                [value, ymax, zmax],
                [value, ymin, zmax],
                [value, ymin, zmin],
            ],
            dtype=np.float32,
        )
        fill_vertices = np.array(
            [
                [value, ymin, zmin],
                [value, ymax, zmin],
                [value, ymax, zmax],
                [value, ymin, zmax],
            ],
            dtype=np.float32,
        )

    return _SliceOverlayGeometry(
        line_vertices=line_vertices,
        fill_vertices=fill_vertices,
        fill_faces=np.array([[0, 1, 2], [0, 2, 3]], dtype=np.uint32),
    )


def _with_alpha(color, alpha: float):
    rgba = list(Color(color).rgba)
    rgba[3] = min(1.0, max(0.0, float(alpha)))
    return tuple(rgba)
