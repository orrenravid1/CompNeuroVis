"""Run the app-local morphology tool composition without installing a plugin."""

from __future__ import annotations

import numpy as np

import compneurovis as cnv

from morphology_tools import MorphologyChannel, MorphologyTools


def demo_geometry() -> cnv.MorphologyGeometry:
    positions = np.asarray(
        [
            (0.0, 0.0, 0.0),
            (0.0, 0.0, 3.0),
            (0.0, 0.0, 6.0),
            (-2.0, 0.0, 8.0),
            (-4.0, 0.0, 10.0),
            (2.0, 0.0, 8.0),
            (4.0, 0.0, 10.0),
            (0.0, -2.0, 8.0),
            (0.0, -4.0, 10.0),
            (0.0, 2.0, 8.0),
            (0.0, 4.0, 10.0),
        ],
        dtype=np.float32,
    )
    count = len(positions)
    entity_ids = tuple(f"segment-{index}" for index in range(count))
    return cnv.MorphologyGeometry(
        id="demo_morphology",
        positions=positions,
        orientations=np.asarray([np.eye(3)] * count, dtype=np.float32),
        radii=np.linspace(1.2, 0.35, count, dtype=np.float32),
        lengths=np.linspace(2.4, 1.3, count, dtype=np.float32),
        entity_ids=entity_ids,
        section_names=entity_ids,
        xlocs=np.full(count, 0.5, dtype=np.float32),
        labels=entity_ids,
    )


geometry = demo_geometry()
phase = np.linspace(0.0, 1.4, len(geometry.entity_ids), dtype=np.float32)
voltage = np.full(len(geometry.entity_ids), -65.0, dtype=np.float32)
sodium = np.zeros_like(voltage)
potassium = np.zeros_like(voltage)
current = np.zeros_like(voltage)
state = {"time": 0.0, "selected_index": 0}


def step(_ctx) -> None:
    state["time"] += 1.0 / 60.0
    wave = np.sin(2.5 * state["time"] - phase)
    voltage[:] = -62.0 + 28.0 * np.maximum(wave, 0.0) ** 5
    sodium[:] = 0.2 + 0.8 * np.maximum(wave, 0.0)
    potassium[:] = 0.15 + 0.7 * np.maximum(-wave, 0.0)
    current[:] = sodium * np.maximum(voltage + 55.0, 0.0)


src = cnv.source(step)
mode = src.dropdown(
    "tool mode",
    label="Click mode",
    options=("select", "paint", "mark"),
    default="select",
)
paint_weight = src.slider(
    "paint weight",
    label="Paint weight",
    min=0.0,
    max=1.0,
    default=0.7,
)
marker_color = src.dropdown(
    "marker color",
    label="Marker color",
    options=("red", "green", "gold", "purple"),
    default="gold",
)

morphology = src.morphology(
    geometry,
    name="Morphology workbench",
    read=lambda: voltage,
    unit="mV",
    color_limits=(-70.0, 20.0),
    color_map="bwr",
    selectable=True,
)
src.add(
    MorphologyChannel(
        morphology,
        "Sodium conductance",
        geometry.entity_ids,
        read=lambda: sodium,
        color="#00a6ff",
        offset=(-0.7, 0.0, 0.0),
    )
)
src.add(
    MorphologyChannel(
        morphology,
        "Potassium conductance",
        geometry.entity_ids,
        read=lambda: potassium,
        color="#8b5cf6",
        offset=(0.7, 0.0, 0.0),
    )
)
src.add(
    MorphologyChannel(
        morphology,
        "Sodium current",
        geometry.entity_ids,
        read=lambda: current,
        color="#00c853",
        offset=(0.0, 0.7, 0.0),
        size=8.0,
    )
)
src.add(
    MorphologyTools(
        morphology,
        geometry.entity_ids,
        mode=mode,
        weight=paint_weight,
        marker_color=marker_color,
    )
)


def follow_selection(ctx, entity_id: str) -> bool:
    if ctx.get_value(mode) != "select":
        return False
    info = ctx.entity_info(entity_id)
    if info is not None:
        state["selected_index"] = int(info["index"])
    return False


src.interactions(entity_click=follow_selection)
selected_voltage = src.line(
    "Selected voltage",
    read=lambda: float(voltage[state["selected_index"]]),
    x=lambda: state["time"],
    y_label="mV",
    max_samples=1200,
)

cnv.layout(((morphology, selected_voltage), (src.controls_panel,)))
cnv.show(title="App-local morphology tools")
