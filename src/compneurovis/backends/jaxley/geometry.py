from __future__ import annotations

import numpy as np

from compneurovis.core.geometry import MorphologyGeometrySpec


def _split_xyzr_into_equal_length_segments(xyzr: np.ndarray, ncomp: int) -> list[np.ndarray]:
    if len(xyzr) == 1:
        return [xyzr] * ncomp

    xyz = xyzr[:, :3]
    deltas = np.diff(xyz, axis=0)
    dists = np.linalg.norm(deltas, axis=1)
    cum_dists = np.concatenate([[0.0], np.cumsum(dists)])
    total_length = cum_dists[-1]
    target_dists = np.linspace(0.0, total_length, ncomp + 1)

    idxs = np.searchsorted(cum_dists, target_dists, side="right") - 1
    idxs = np.clip(idxs, 0, len(xyz) - 2)
    local_dist = target_dists - cum_dists[idxs]
    dists = np.where(dists < 1e-14, 1e-14, dists)
    segment_lens = dists[idxs]
    frac = (local_dist / segment_lens)[:, None]
    split_points = xyzr[idxs] + frac * (xyzr[idxs + 1] - xyzr[idxs])

    segments = []
    all_points = [split_points[0]]
    for i in range(1, len(split_points)):
        mask = (cum_dists > target_dists[i - 1]) & (cum_dists < target_dists[i])
        between_points = xyzr[mask]
        segment = np.vstack([all_points[-1], *between_points, split_points[i]])
        segments.append(segment.astype(np.float32))
        all_points.append(split_points[i])
    return segments


def _segment_radius(segment_xyzr: np.ndarray) -> float:
    if len(segment_xyzr) <= 1:
        return float(segment_xyzr[0, 3])
    lengths = np.linalg.norm(np.diff(segment_xyzr[:, :3], axis=0), axis=1)
    weights = np.zeros((len(segment_xyzr),), dtype=np.float32)
    weights[1:] += lengths
    weights[:-1] += lengths
    total = float(weights.sum())
    if total <= 1e-12:
        return float(np.mean(segment_xyzr[:, 3]))
    weights /= total
    return float(np.sum(segment_xyzr[:, 3] * weights))


def build_morphology_geometry(
    nodes,
    *,
    xyzr: list[np.ndarray] | tuple[np.ndarray, ...] | None = None,
    cell_names: list[str] | tuple[str, ...] | None = None,
) -> MorphologyGeometrySpec:
    """Convert Jaxley morphology/network data into MorphologyGeometrySpec."""

    ordered = nodes.sort_values("global_comp_index").reset_index(drop=True)
    if ordered.empty:
        raise ValueError("Jaxley morphology geometry requires at least one compartment")

    positions = ordered[["x", "y", "z"]].to_numpy(np.float32)
    lengths = np.maximum(ordered["length"].to_numpy(np.float32), 1e-6)
    radii = np.maximum(ordered["radius"].to_numpy(np.float32), 1e-6)
    directions = np.repeat(np.array([[0.0, 0.0, 1.0]], dtype=np.float32), len(ordered), axis=0)

    for branch_idx, branch in ordered.groupby("global_branch_index", sort=False):
        idxs = branch.index.to_numpy()
        if xyzr is not None and int(branch_idx) < len(xyzr):
            branch_xyzr = np.asarray(xyzr[int(branch_idx)], dtype=np.float32)
            segments = _split_xyzr_into_equal_length_segments(branch_xyzr, len(idxs))
            branch_positions = []
            branch_lengths = []
            branch_radii = []
            branch_dirs = []
            for segment in segments:
                start = segment[0, :3]
                end = segment[-1, :3]
                diff = end - start
                seg_length = float(np.linalg.norm(diff))
                if seg_length <= 1e-6:
                    seg_dir = np.array([0.0, 0.0, 1.0], dtype=np.float32)
                    seg_length = 1e-6
                else:
                    seg_dir = diff / seg_length
                branch_positions.append(0.5 * (start + end))
                branch_lengths.append(seg_length)
                branch_radii.append(max(_segment_radius(segment), 1e-6))
                branch_dirs.append(seg_dir)
            positions[idxs] = np.asarray(branch_positions, dtype=np.float32)
            lengths[idxs] = np.asarray(branch_lengths, dtype=np.float32)
            radii[idxs] = np.asarray(branch_radii, dtype=np.float32)
            directions[idxs] = np.asarray(branch_dirs, dtype=np.float32)
        else:
            pts = branch[["x", "y", "z"]].to_numpy(np.float32)
            if len(idxs) == 1:
                continue
            branch_dirs = np.zeros_like(pts)
            branch_dirs[:-1] = pts[1:] - pts[:-1]
            branch_dirs[-1] = pts[-1] - pts[-2]
            norms = np.linalg.norm(branch_dirs, axis=1, keepdims=True)
            nonzero = norms[:, 0] > 1e-6
            branch_dirs[nonzero] = branch_dirs[nonzero] / norms[nonzero]
            branch_dirs[~nonzero] = np.array([0.0, 0.0, 1.0], dtype=np.float32)
            directions[idxs] = branch_dirs

    cos_t = directions[:, 2]
    ang = np.arccos(np.clip(cos_t, -1.0, 1.0))
    ax = np.cross(np.repeat([[0.0, 0.0, 1.0]], len(directions), axis=0), directions)
    ax_n = np.linalg.norm(ax, axis=1, keepdims=True)
    ax_u = np.zeros_like(ax)
    np.divide(ax, ax_n, out=ax_u, where=ax_n > 1e-6)
    ux, uy, uz = ax_u.T

    k = np.zeros((len(directions), 3, 3), dtype=np.float32)
    k[:, 0, 1] = -uz
    k[:, 0, 2] = uy
    k[:, 1, 0] = uz
    k[:, 1, 2] = -ux
    k[:, 2, 0] = -uy
    k[:, 2, 1] = ux
    k2 = k @ k
    identity = np.eye(3, dtype=np.float32)[None, :, :]
    orientations = identity + np.sin(ang)[:, None, None] * k + (1.0 - cos_t)[:, None, None] * k2

    global_cell = ordered["global_cell_index"].to_numpy(np.int32)
    local_branch = ordered["local_branch_index"].to_numpy(np.int32)
    local_comp = ordered["local_comp_index"].to_numpy(np.float32)
    counts = ordered.groupby("global_branch_index")["global_comp_index"].transform("size").to_numpy(np.float32)
    xlocs = (local_comp + 0.5) / np.maximum(counts, 1.0)

    if cell_names is None:
        names = {int(cell_idx): f"cell_{int(cell_idx)}" for cell_idx in np.unique(global_cell)}
    else:
        names = {int(cell_idx): str(cell_names[int(cell_idx)]) for cell_idx in np.unique(global_cell)}
    section_names = tuple(
        f"{names[int(cell_idx)]}_branch_{int(branch_idx)}"
        for cell_idx, branch_idx in zip(global_cell, local_branch)
    )
    labels = tuple(f"{section}@{float(xloc):.3f}" for section, xloc in zip(section_names, xlocs))

    return MorphologyGeometrySpec(
        id="morphology",
        positions=positions.astype(np.float32),
        orientations=orientations.astype(np.float32),
        radii=radii.astype(np.float32),
        lengths=lengths.astype(np.float32),
        entity_ids=labels,
        section_names=section_names,
        xlocs=xlocs.astype(np.float32),
        labels=labels,
    )


__all__ = ["build_morphology_geometry"]