from __future__ import annotations

import time

import numpy as np

from compneurovis.geometries.morphology import MorphologyGeometry
from compneurovis.frontends.vispy.renderers.colormaps import _colormap_samples
from compneurovis.components.morphology.cylinders import CappedCylinderCollection


_CPU_PICK_SEGMENT_LIMIT = 25_000


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
        """Pick the nearest capped cylinder without a synchronous GPU readback."""
        if self.collection is None or self.geometry is None:
            return None
        if len(self.geometry.entity_ids) > _CPU_PICK_SEGMENT_LIMIT:
            return self._pick_gpu(xf, yf, canvas)
        try:
            origin, direction = self._canvas_ray(xf, yf, canvas)
            index = _nearest_capped_cylinder(
                origin,
                direction,
                self.geometry.positions,
                self.geometry.orientations[:, :, 2],
                self.geometry.radii,
                self.geometry.lengths,
            )
        except (AttributeError, TypeError, ValueError, np.linalg.LinAlgError):
            return self._pick_gpu(xf, yf, canvas)
        return None if index is None else self.geometry.entity_ids[index]

    def _canvas_ray(self, xf, yf, canvas) -> tuple[np.ndarray, np.ndarray]:
        pixel_scale = max(float(canvas.pixel_scale), 1e-12)
        x = float(xf) / pixel_scale
        y = float(canvas.size[1]) - float(yf) / pixel_scale - 1.0
        transform = self.view.scene.node_transform(canvas.scene)

        def unproject(z: float) -> np.ndarray:
            point = np.asarray(transform.imap((x, y, z, 1.0)), dtype=np.float64)
            if point.shape[-1] == 4:
                if abs(point[3]) < 1e-12:
                    raise ValueError("Cannot unproject a point with zero homogeneous w")
                point = point[:3] / point[3]
            return point[:3]

        origin = unproject(-1.0)
        far = unproject(1.0)
        direction = far - origin
        length = float(np.linalg.norm(direction))
        if length < 1e-12:
            raise ValueError("Cannot construct a zero-length picking ray")
        return origin, direction / length

    def _pick_gpu(self, xf, yf, canvas) -> str | None:
        if self.collection is None or self.geometry is None:
            return None
        side, cap = self.collection._side_mesh, self.collection._cap_mesh
        old_side, old_cap = side.instance_colors, cap.instance_colors
        siblings = [
            child
            for child in tuple(self.view.scene.children)
            if child is not self.collection
        ]
        sibling_visibility = [bool(child.visible) for child in siblings]
        try:
            for child in siblings:
                child.visible = False
            side.instance_colors = self.id_colors
            cap.instance_colors = self.id_colors_caps
            img = canvas.render(region=(xf, yf, 1, 1), size=(1, 1), alpha=False)
        finally:
            side.instance_colors, cap.instance_colors = old_side, old_cap
            for child, visible in zip(siblings, sibling_visibility):
                child.visible = visible
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


def _nearest_capped_cylinder(
    ray_origin: np.ndarray,
    ray_direction: np.ndarray,
    centers: np.ndarray,
    axes: np.ndarray,
    radii: np.ndarray,
    lengths: np.ndarray,
) -> int | None:
    """Return the nearest finite-cylinder intersection using vectorized NumPy."""
    origin = np.asarray(ray_origin, dtype=np.float64)
    direction = np.asarray(ray_direction, dtype=np.float64)
    center = np.asarray(centers, dtype=np.float64)
    axis = np.asarray(axes, dtype=np.float64)
    radius = np.asarray(radii, dtype=np.float64)
    half_length = np.asarray(lengths, dtype=np.float64) * 0.5
    if center.size == 0:
        return None

    axis_norm = np.linalg.norm(axis, axis=1)
    valid_axis = axis_norm > 1e-12
    axis = axis / np.where(valid_axis, axis_norm, 1.0)[:, None]
    offset = origin[None, :] - center
    d_axis = axis @ direction
    o_axis = np.einsum("ij,ij->i", offset, axis)
    d_perp = direction[None, :] - d_axis[:, None] * axis
    o_perp = offset - o_axis[:, None] * axis

    a = np.einsum("ij,ij->i", d_perp, d_perp)
    b = 2.0 * np.einsum("ij,ij->i", d_perp, o_perp)
    c = np.einsum("ij,ij->i", o_perp, o_perp) - radius * radius
    discriminant = b * b - 4.0 * a * c
    valid_side = valid_axis & (a > 1e-12) & (discriminant >= 0.0)
    sqrt_disc = np.sqrt(np.maximum(discriminant, 0.0))
    denominator = np.where(valid_side, 2.0 * a, 1.0)
    side_roots = np.stack(
        ((-b - sqrt_disc) / denominator, (-b + sqrt_disc) / denominator),
        axis=1,
    )
    side_axis = o_axis[:, None] + side_roots * d_axis[:, None]
    side_valid = (
        valid_side[:, None]
        & (side_roots >= 0.0)
        & (np.abs(side_axis) <= half_length[:, None] + 1e-9)
    )
    side_t = np.min(np.where(side_valid, side_roots, np.inf), axis=1)

    cap_denominator = np.where(np.abs(d_axis) > 1e-12, d_axis, 1.0)
    cap_t = np.stack(
        ((-half_length - o_axis) / cap_denominator,
         (half_length - o_axis) / cap_denominator),
        axis=1,
    )
    cap_points = offset[:, None, :] + cap_t[:, :, None] * direction
    cap_radial = cap_points - np.einsum(
        "nij,nj->ni", cap_points, axis
    )[:, :, None] * axis[:, None, :]
    cap_valid = (
        valid_axis[:, None]
        & (np.abs(d_axis) > 1e-12)[:, None]
        & (cap_t >= 0.0)
        & (
            np.einsum("nij,nij->ni", cap_radial, cap_radial)
            <= radius[:, None] * radius[:, None] + 1e-9
        )
    )
    cap_nearest = np.min(np.where(cap_valid, cap_t, np.inf), axis=1)
    distance = np.minimum(side_t, cap_nearest)
    index = int(np.argmin(distance))
    return None if not np.isfinite(distance[index]) else index
