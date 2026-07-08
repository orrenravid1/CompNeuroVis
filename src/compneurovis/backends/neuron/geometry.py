from __future__ import annotations

import time

import numpy as np

from compneurovis.core.geometry import MorphologyGeometrySpec


def build_morphology_geometry(sections) -> MorphologyGeometrySpec:
    """Convert NEURON sections with pt3d data into MorphologyGeometrySpec."""

    t0 = time.perf_counter()

    if any(int(sec.n3d()) < 2 for sec in sections):
        from compneurovis.backends.neuron.utils import generate_layout

        generate_layout(sections)

    sec_names = []
    p0s, p1s, d0s, d1s = [], [], [], []
    cums, totals, sec_idx = [], [], []

    for si, sec in enumerate(sections):
        n3d = int(sec.n3d())
        if n3d < 2:
            continue
        sec_names.append(sec.name())
        pts = np.stack([[sec.x3d(i), sec.y3d(i), sec.z3d(i)] for i in range(n3d)], axis=0).astype(np.float32)
        diams = np.array([sec.diam3d(i) for i in range(n3d)], dtype=np.float32)
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

    elapsed = time.perf_counter() - t0
    print(f"Meta file generated in {elapsed:.2f}s")

    return MorphologyGeometrySpec(
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