from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

import numpy as np

from compneurovis.geometries.morphology import MorphologyGeometry


def _interpolate_polyline(
    points: np.ndarray,
    diameters: np.ndarray,
    xloc: float,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Interpolate display geometry without modifying its owning section."""

    diffs = np.diff(points, axis=0)
    segment_lengths = np.linalg.norm(diffs, axis=1)
    cumulative = np.concatenate(([0.0], np.cumsum(segment_lengths)))
    total = float(cumulative[-1])
    if total <= 1e-12:
        return (
            points[0].copy(),
            np.array([0.0, 0.0, 1.0], dtype=np.float64),
            float(diameters[0]),
        )

    target = float(np.clip(xloc, 0.0, 1.0)) * total
    segment_index = int(np.searchsorted(cumulative, target, side="right")) - 1
    segment_index = max(0, min(segment_index, len(points) - 2))
    segment_length = float(segment_lengths[segment_index])
    fraction = (
        0.0
        if segment_length <= 1e-12
        else (target - cumulative[segment_index]) / segment_length
    )
    direction = diffs[segment_index]
    direction_length = float(np.linalg.norm(direction))
    direction = (
        direction / direction_length
        if direction_length > 1e-12
        else np.array([0.0, 0.0, 1.0], dtype=np.float64)
    )
    position = points[segment_index] + fraction * diffs[segment_index]
    diameter = diameters[segment_index] + fraction * (
        diameters[segment_index + 1] - diameters[segment_index]
    )
    return position, direction, float(diameter)


def _fan_direction(
    parent_direction: np.ndarray,
    sibling_index: int,
    sibling_count: int,
) -> np.ndarray:
    """Give synthetic sibling branches distinct, deterministic directions."""

    direction = np.asarray(parent_direction, dtype=np.float64)
    length = float(np.linalg.norm(direction))
    direction = (
        direction / length
        if length > 1e-12
        else np.array([0.0, 0.0, 1.0], dtype=np.float64)
    )
    if sibling_count <= 1:
        return direction

    auxiliary = np.array(
        [1.0, 0.0, 0.0] if abs(direction[0]) < 0.9 else [0.0, 1.0, 0.0],
        dtype=np.float64,
    )
    perpendicular = np.cross(direction, auxiliary)
    perpendicular /= np.linalg.norm(perpendicular)
    second_perpendicular = np.cross(direction, perpendicular)
    azimuth = 2.0 * np.pi * sibling_index / sibling_count
    radial = (
        np.cos(azimuth) * perpendicular
        + np.sin(azimuth) * second_perpendicular
    )
    angle = np.deg2rad(30.0)
    child = np.cos(angle) * direction + np.sin(angle) * radial
    return child / np.linalg.norm(child)


def _visual_section_geometry(
    sections: Sequence[object],
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Return real or synthetic pt3d arrays owned only by the visualization.

    NEURON treats pt3d as model state. Geometry adaptation therefore must not
    call ``define_shape()``, ``pt3dclear()``, or ``pt3dadd()``. Sections with
    fewer than two points receive a two-point display fallback based on their
    topology, length, and diameter; existing pt3d arrays pass through unchanged.
    """

    names = [section.name() for section in sections]
    section_by_name = dict(zip(names, sections))
    existing: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    single_points: dict[str, tuple[np.ndarray, float]] = {}
    for name, section in zip(names, sections):
        point_count = int(section.n3d())
        if point_count == 0:
            continue
        points = np.asarray(
            [
                [section.x3d(i), section.y3d(i), section.z3d(i)]
                for i in range(point_count)
            ],
            dtype=np.float64,
        )
        diameters = np.asarray(
            [section.diam3d(i) for i in range(point_count)],
            dtype=np.float64,
        )
        if point_count >= 2:
            existing[name] = (points, diameters)
        else:
            single_points[name] = (points[0], float(diameters[0]))

    parent_by_name: dict[str, tuple[str, float]] = {}
    siblings: dict[tuple[str, float], list[str]] = defaultdict(list)
    for name, section in zip(names, sections):
        parent_segment = section.parentseg()
        if parent_segment is None:
            continue
        parent_name = parent_segment.sec.name()
        if parent_name not in section_by_name:
            continue
        connection = (parent_name, float(parent_segment.x))
        parent_by_name[name] = connection
        if name not in existing:
            siblings[connection].append(name)

    fallback_roots = [
        name
        for name in names
        if name not in existing
        and name not in single_points
        and name not in parent_by_name
    ]
    existing_x = [
        float(point[0])
        for points, _ in existing.values()
        for point in points
    ]
    root_base_x = max(existing_x) + 100.0 if existing_x else 0.0
    root_positions = {
        name: np.array(
            [root_base_x + 100.0 * index, 0.0, 0.0],
            dtype=np.float64,
        )
        for index, name in enumerate(fallback_roots)
    }

    resolved = dict(existing)
    resolving: set[str] = set()

    def resolve(name: str) -> tuple[np.ndarray, np.ndarray]:
        if name in resolved:
            return resolved[name]
        if name in resolving:
            raise ValueError(f"Cycle detected in NEURON section topology at {name!r}")
        resolving.add(name)
        section = section_by_name[name]
        diameter = max(float(section.diam), 1e-6)
        length = max(float(section.L), 1.0)

        if name in parent_by_name:
            connection = parent_by_name[name]
            parent_points, parent_diameters = resolve(connection[0])
            start, parent_direction, _ = _interpolate_polyline(
                parent_points, parent_diameters, connection[1]
            )
            peers = siblings[connection]
            direction = _fan_direction(
                parent_direction, peers.index(name), len(peers)
            )
        else:
            start = root_positions.get(
                name, np.array([root_base_x, 0.0, 0.0], dtype=np.float64)
            )
            direction = np.array([0.0, 0.0, 1.0], dtype=np.float64)

        if name in single_points:
            start, diameter = single_points[name]
        result = (
            np.stack((start, start + direction * length), axis=0),
            np.asarray((diameter, diameter), dtype=np.float64),
        )
        resolving.remove(name)
        resolved[name] = result
        return result

    return [resolve(name) for name in names]


def build_morphology_geometry(sections) -> MorphologyGeometry:
    """Convert NEURON sections into non-owning morphology geometry."""

    sections = list(sections)
    visual_geometry = _visual_section_geometry(sections)

    sec_names = []
    p0s, p1s, d0s, d1s = [], [], [], []
    cums, totals, sec_idx = [], [], []

    for si, (sec, (pts, diams)) in enumerate(zip(sections, visual_geometry)):
        sec_names.append(sec.name())
        pts = np.asarray(pts, dtype=np.float32)
        diams = np.asarray(diams, dtype=np.float32)
        diffs = pts[1:] - pts[:-1]
        dlen = np.linalg.norm(diffs, axis=1)
        cum = np.concatenate(([0.0], np.cumsum(dlen)))[:-1]
        total = cum[-1] + dlen[-1] if dlen.sum() > 0 else 1.0

        p0s.append(pts[:-1])
        p1s.append(pts[1:])
        d0s.append(diams[:-1])
        d1s.append(diams[1:])
        cums.append(cum)
        totals.append(np.full_like(dlen, total, dtype=np.float32))
        sec_idx.append(np.full_like(dlen, si, dtype=np.int32))

    p0 = np.vstack(p0s)
    p1 = np.vstack(p1s)
    d0 = np.concatenate(d0s)
    d1 = np.concatenate(d1s)
    cum = np.concatenate(cums)
    total = np.concatenate(totals)
    si = np.concatenate(sec_idx)
    n_segments = p0.shape[0]

    mid = 0.5 * (p0 + p1)
    lengths = np.linalg.norm(p1 - p0, axis=1)
    xloc = (cum + 0.5 * lengths) / total
    radii = 0.5 * (d0 + d1)

    diffs = p1 - p0
    lengths_safe = np.linalg.norm(diffs, axis=1)
    dn = np.zeros_like(diffs)
    nonzero = lengths_safe > 1e-8
    dn[nonzero] = diffs[nonzero] / lengths_safe[nonzero, None]
    cos_t = dn[:, 2]
    ang = np.arccos(np.clip(cos_t, -1.0, 1.0))
    ax = np.cross(np.repeat([[0, 0, 1]], n_segments, axis=0), dn)
    ax_n = np.linalg.norm(ax, axis=1, keepdims=True)
    ax_u = np.zeros_like(ax)
    np.divide(ax, ax_n, out=ax_u, where=(ax_n > 1e-6))
    ux, uy, uz = ax_u.T

    k = np.zeros((n_segments, 3, 3), dtype=np.float32)
    k[:, 0, 1] = -uz
    k[:, 0, 2] = uy
    k[:, 1, 0] = uz
    k[:, 1, 2] = -ux
    k[:, 2, 0] = -uy
    k[:, 2, 1] = ux
    k2 = k @ k
    identity = np.eye(3, dtype=np.float32)[None, :, :]
    orientations = identity + np.sin(ang)[:, None, None] * k + (1.0 - cos_t)[:, None, None] * k2

    entity_ids = tuple(f"{sec_names[idx]}@{float(x):.5f}" for idx, x in zip(si, xloc))
    section_labels = tuple(sec_names[idx] for idx in si)

    return MorphologyGeometry(
        id="morphology",
        positions=mid.astype(np.float32),
        orientations=orientations.astype(np.float32),
        radii=radii.astype(np.float32),
        lengths=lengths.astype(np.float32),
        entity_ids=entity_ids,
        section_names=section_labels,
        xlocs=xloc.astype(np.float32),
        labels=entity_ids,
    )


__all__ = ["build_morphology_geometry"]
