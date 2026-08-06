from __future__ import annotations

import time

import numpy as np

from compneurovis.inline.widgets.morphology_geometry import MorphologyGeometry
from compneurovis.frontends.vispy.renderers.colormaps import _colormap_samples
from compneurovis.frontends.vispy.utils.capped_cylinder_collection import CappedCylinderCollection


class MorphologyRenderer:
    def __init__(self, view):
        self.view = view
        self.geometry: MorphologyGeometry | None = None
        self.collection = None
        self._color_buf = None
        self.id_colors = None
        self.id_colors_caps = None

    def clear(self) -> None:
        if self.collection is not None:
            self.collection.parent = None
            self.collection = None
        self.geometry = None
        self._color_buf = None
        self.id_colors = None
        self.id_colors_caps = None

    def set_geometry(self, geometry: MorphologyGeometry) -> None:
        self.geometry = geometry
        if self.collection is not None:
            self.collection.parent = None
        colors = geometry.colors
        if colors is None:
            colors = np.tile(np.array([0.7, 0.7, 0.7, 1.0], dtype=np.float32), (len(geometry.entity_ids), 1))

        t0 = time.perf_counter()
        self.collection = CappedCylinderCollection(
            positions=geometry.positions,
            radii=geometry.radii,
            heights=geometry.lengths,
            orientations=geometry.orientations,
            colors=colors,
            cylinder_segments=32,
            disk_slices=32,
            parent=self.view.scene,
        )
        self.collection._side_mesh.shading = None
        self.collection._cap_mesh.shading = None

        n = len(geometry.entity_ids)
        self._color_buf = np.empty((n, 4), dtype=np.float32)
        self._color_buf[:, 1] = 0.2
        self._color_buf[:, 3] = 1.0

        def make_id_color(i):
            cid = i + 1
            return np.array(
                [
                    (cid & 0xFF) / 255.0,
                    ((cid >> 8) & 0xFF) / 255.0,
                    ((cid >> 16) & 0xFF) / 255.0,
                    1.0,
                ],
                dtype=np.float32,
            )

        self.id_colors = np.stack([make_id_color(i) for i in range(n)], axis=0)
        self.id_colors_caps = np.vstack([self.id_colors, self.id_colors])
        elapsed = time.perf_counter() - t0
        print(f"Morphology visual generated in {elapsed:.2f}s")

    def pick(self, xf, yf, canvas) -> str | None:
        if self.collection is None or self.geometry is None:
            return None
        side, cap = self.collection._side_mesh, self.collection._cap_mesh
        old_side, old_cap = side.instance_colors, cap.instance_colors
        side.instance_colors = self.id_colors
        cap.instance_colors = self.id_colors_caps
        img = canvas.render(region=(xf, yf, 1, 1), size=(1, 1), alpha=False)
        side.instance_colors, cap.instance_colors = old_side, old_cap
        idx = self._decode_pick_index(img)
        if idx is None or idx >= len(self.geometry.entity_ids):
            return None
        return self.geometry.entity_ids[idx]

    def _decode_pick_index(self, img: np.ndarray) -> int | None:
        pixels = np.asarray(img)
        if pixels.ndim != 3 or pixels.shape[2] < 3 or pixels.shape[0] == 0 or pixels.shape[1] == 0:
            return None
        if pixels.dtype != np.uint8:
            pixels = np.round(pixels * 255).astype(np.uint8)
        pix = pixels[0, 0]
        cid = int(pix[0]) | (int(pix[1]) << 8) | (int(pix[2]) << 16)
        return cid - 1 if cid > 0 else None

    def update_colors(self, data: np.ndarray, color_map: str, *, color_limits=None, color_norm: str = "auto") -> None:
        if self.collection is None:
            return
        values = np.asarray(data, dtype=np.float32)
        if color_limits is not None:
            vmin, vmax = float(color_limits[0]), float(color_limits[1])
            if abs(vmax - vmin) < 1e-12:
                norm = np.zeros_like(values, dtype=np.float32)
            else:
                norm = np.clip((values - vmin) / (vmax - vmin), 0.0, 1.0)
        elif color_norm == "symmetric":
            vmax = float(np.max(np.abs(values)))
            if vmax < 1e-12:
                norm = np.full_like(values, 0.5, dtype=np.float32)
            else:
                norm = np.clip((values + vmax) / (2.0 * vmax), 0.0, 1.0)
        else:
            vmin = float(np.min(values))
            vmax = float(np.max(values))
            if abs(vmax - vmin) < 1e-12:
                norm = np.zeros_like(values, dtype=np.float32)
            else:
                norm = np.clip((values - vmin) / (vmax - vmin), 0.0, 1.0)
        if str(color_map).strip().lower() == "scalar":
            self._color_buf[:, 0] = norm
            self._color_buf[:, 1] = 0.2
            self._color_buf[:, 2] = 1.0 - norm
            self._color_buf[:, 3] = 1.0
        else:
            lut = _colormap_samples(color_map)
            idx = np.clip((norm * (len(lut) - 1)).astype(np.int32), 0, len(lut) - 1)
            self._color_buf[:, :] = lut[idx]
        self.collection.set_colors(self._color_buf)
