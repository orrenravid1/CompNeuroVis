"""Morphology widget: custom geometry with selectable per-segment values.

This uses ``cnv.source().morphology(...)`` directly. The geometry is a tiny
branched cable built from arrays, so the example has no external simulator
requirement. Click a segment to change the selected-segment trace.

Run: python examples/widgets/morphology.py
"""

from __future__ import annotations

import numpy as np

import compneurovis as cnv


GEOMETRY_SCALE = 70.0
DEFAULT_SELECTED = "primary"


def _orientation_from_z(direction: np.ndarray) -> np.ndarray:
    direction = direction.astype(np.float32)
    norm = float(np.linalg.norm(direction))
    if norm <= 1e-8:
        return np.eye(3, dtype=np.float32)
    target = direction / norm
    source = np.asarray([0.0, 0.0, 1.0], dtype=np.float32)
    cross = np.cross(source, target)
    dot = float(np.clip(np.dot(source, target), -1.0, 1.0))
    cross_norm = float(np.linalg.norm(cross))
    if cross_norm <= 1e-8:
        return np.eye(3, dtype=np.float32) if dot > 0.0 else np.diag([1.0, -1.0, -1.0]).astype(np.float32)
    axis = cross / cross_norm
    ux, uy, uz = axis
    k = np.asarray(
        [[0.0, -uz, uy], [uz, 0.0, -ux], [-uy, ux, 0.0]],
        dtype=np.float32,
    )
    angle = float(np.arccos(dot))
    return (np.eye(3, dtype=np.float32) + np.sin(angle) * k + (1.0 - np.cos(angle)) * (k @ k)).astype(np.float32)


def _geometry() -> cnv.MorphologyGeometrySpec:
    segments = (
        ("soma", (-0.55, 0.0, 0.0), (0.55, 0.0, 0.0), 0.18),
        ("primary", (0.55, 0.0, 0.0), (1.55, 0.0, 0.0), 0.09),
        ("upper", (1.55, 0.0, 0.0), (2.25, 0.55, 0.0), 0.065),
        ("middle", (1.55, 0.0, 0.0), (2.35, 0.0, 0.0), 0.055),
        ("lower", (1.55, 0.0, 0.0), (2.25, -0.55, 0.0), 0.065),
    )
    starts = GEOMETRY_SCALE * np.asarray([item[1] for item in segments], dtype=np.float32)
    ends = GEOMETRY_SCALE * np.asarray([item[2] for item in segments], dtype=np.float32)
    directions = ends - starts
    lengths = np.linalg.norm(directions, axis=1).astype(np.float32)
    positions = (0.5 * (starts + ends)).astype(np.float32)
    orientations = np.stack([_orientation_from_z(direction) for direction in directions], axis=0)
    radii = GEOMETRY_SCALE * np.asarray([item[3] for item in segments], dtype=np.float32)
    entity_ids = tuple(item[0] for item in segments)

    return cnv.MorphologyGeometrySpec(
        id="branched_cable",
        positions=positions,
        orientations=orientations,
        radii=radii,
        lengths=lengths,
        entity_ids=entity_ids,
        section_names=entity_ids,
        xlocs=np.linspace(0.1, 0.9, len(entity_ids), dtype=np.float32),
        labels=entity_ids,
    )


geometry = _geometry()
activity = np.asarray([0.15, 0.45, 0.78, 0.62, 0.36], dtype=np.float32)
activity_by_entity = dict(zip(geometry.entity_ids, activity.tolist()))


class SelectionProbe:
    def __init__(self) -> None:
        self.t = 0.0
        self.activity = activity_by_entity[DEFAULT_SELECTED]

    def step(self, ctx) -> None:
        self.t += 16.0
        selected = ctx.get_value(morph.selected, DEFAULT_SELECTED)
        self.activity = activity_by_entity.get(selected, 0.0)


probe = SelectionProbe()
src = cnv.source(probe.step)

morph = src.morphology(
    geometry,
    name="Branched cable",
    values=activity,
    unit="a.u.",
    color_map="aquamarine",
    color_limits=(0.0, 1.0),
    background_color="white",
    selected=DEFAULT_SELECTED,
    selectable=True,
)

selected_trace = src.line(
    "Selected segment activity",
    read={"Activity": lambda: probe.activity},
    x=lambda: probe.t,
    x_label="Time",
    x_unit="ms",
    y_label="Activity",
    y_unit="a.u.",
    y_min=0.0,
    y_max=1.0,
    rolling_window=1200.0,
    trim_to_rolling_window=True,
    color="#0b7f75",
    linewidth=2.5,
    background_color="white",
)

cnv.layout(((morph,selected_trace),))

cnv.show(title="Morphology widget")