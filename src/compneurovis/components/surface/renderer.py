from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from vispy import scene
from vispy.color import Color

from compneurovis.components.surface.axes import SurfaceAxesOverlay
from compneurovis.frontends.vispy.renderers.colormaps import _colormap_samples


class SurfaceRenderer:
    def __init__(self, view):
        self.view = view
        self.surface = None
        self.axes = SurfaceAxesOverlay(view)
        self._grid_shape = None
        self._last_z = None

    def clear(self) -> None:
        if self.surface is not None:
            self.surface.parent = None
            self.surface = None
        self.axes.clear()
        self._grid_shape = None
        self._last_z = None

    def update_surface(
        self,
        x,
        y,
        z,
        *,
        color_map,
        color_limits,
        colors,
        color_by,
        surface_color,
        surface_shading,
        surface_alpha,
        coords_changed=True,
    ):
        x = np.asarray(x, dtype=np.float32)
        y = np.asarray(y, dtype=np.float32)
        z = np.asarray(z, dtype=np.float32)
        self._last_z = z
        appearance = self._surface_appearance(
            z,
            color_map=color_map,
            color_limits=color_limits,
            colors=colors,
            color_by=color_by,
            surface_color=surface_color,
            surface_shading=surface_shading,
            surface_alpha=surface_alpha,
        )
        grid_shape = (tuple(x.shape), tuple(y.shape), tuple(z.shape))
        recreate_surface = self.surface is None or self._grid_shape != grid_shape
        if recreate_surface:
            if self.surface is not None:
                self.surface.parent = None
            self.surface = scene.visuals.SurfacePlot(
                x=x,
                y=y,
                z=z,
                color=appearance.surface_rgba,
                shading=appearance.shading,
                parent=self.view.scene,
            )
            self.surface.set_gl_state("translucent", depth_test=True, cull_face=False)
            self._grid_shape = grid_shape
        else:
            self.surface.shading = appearance.shading
        if coords_changed:
            # Grid shape is the same but x/y coordinates changed - full data upload.
            if appearance.colors is not None:
                self.surface.set_data(x=x, y=y, z=z, colors=appearance.colors)
            else:
                self.surface.set_data(x=x, y=y, z=z)
                self.surface.color = appearance.surface_rgba
        else:
            # Only z (and colors) changed - skip x/y GPU upload.
            if appearance.colors is not None:
                self.surface.set_data(z=z, colors=appearance.colors)
            else:
                self.surface.set_data(z=z)
                self.surface.color = appearance.surface_rgba
        if recreate_surface:
            self.view.camera.set_range()

    def update_surface_style(
        self,
        z,
        *,
        color_map,
        color_limits,
        colors,
        color_by,
        surface_color,
        surface_shading,
        surface_alpha,
    ) -> None:
        if self.surface is None:
            return
        z = np.asarray(z, dtype=np.float32)
        self._last_z = z
        appearance = self._surface_appearance(
            z,
            color_map=color_map,
            color_limits=color_limits,
            colors=colors,
            color_by=color_by,
            surface_color=surface_color,
            surface_shading=surface_shading,
            surface_alpha=surface_alpha,
        )
        self.surface.shading = appearance.shading
        if appearance.colors is not None:
            self.surface.set_data(colors=appearance.colors)
        else:
            self._clear_surface_vertex_colors()
            self.surface.color = appearance.surface_rgba

    def _surface_appearance(
        self,
        z: np.ndarray,
        *,
        color_map,
        color_limits,
        colors,
        color_by,
        surface_color,
        surface_shading,
        surface_alpha,
    ) -> "_SurfaceAppearance":
        color_by_name = str(color_by).strip().lower()
        if colors is None and color_by_name == "height":
            colors = self._map_height_to_colors(z, color_map, color_limits)
        if colors is not None:
            colors = np.asarray(colors, dtype=np.float32).copy()
            if colors.shape[-1] == 4:
                colors[..., 3] = float(surface_alpha)
        return _SurfaceAppearance(
            colors=colors,
            surface_rgba=self._surface_rgba(surface_color, surface_alpha),
            shading=self._resolve_shading(surface_shading),
        )

    def _map_height_to_colors(self, z: np.ndarray, color_map: str, color_limits) -> np.ndarray:
        if color_limits is None:
            zmin = float(np.min(z))
            zmax = float(np.max(z))
        else:
            zmin, zmax = float(color_limits[0]), float(color_limits[1])
        if abs(zmax - zmin) < 1e-12:
            norm = np.zeros_like(z, dtype=np.float32)
        else:
            norm = np.clip((z - zmin) / (zmax - zmin), 0.0, 1.0).astype(np.float32)
        lut = _colormap_samples(color_map)
        idx = np.clip((norm * (len(lut) - 1)).astype(np.int32), 0, len(lut) - 1)
        return lut[idx]

    def _surface_rgba(self, color, surface_alpha: float) -> tuple[float, float, float, float]:
        rgba = list(Color(color).rgba)
        rgba[3] = float(surface_alpha)
        return tuple(rgba)

    def _resolve_shading(self, shading):
        if shading is None:
            return None
        name = str(shading).strip().lower()
        if name in {"", "none", "unlit"}:
            return None
        if name in {"lit", "smooth"}:
            return "smooth"
        if name == "flat":
            return "flat"
        return name

    def _clear_surface_vertex_colors(self) -> None:
        if self.surface is None:
            return
        mesh_data = self.surface.mesh_data
        mesh_data._vertex_colors = None
        mesh_data._vertex_colors_indexed_by_faces = None
        mesh_data._vertex_colors_indexed_by_edges = None


@dataclass(slots=True)
class _SurfaceAppearance:
    colors: np.ndarray | None
    surface_rgba: tuple[float, float, float, float]
    shading: str | None
