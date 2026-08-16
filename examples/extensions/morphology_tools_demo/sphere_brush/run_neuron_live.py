"""Live NEURON morphology with app-local spatial parameter painting.

Live mode displays a selected simulation variable. Paint mode instead owns the
displayed parameter, colormap, brush cursor, and target-specific controls; click
or drag to write the selected segment- or section-owned parameter.

Requires NEURON and ``res/Animal_2_Basal_2.CNG.swc``.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

import compneurovis as cnv
import numpy as np
from compneurovis.backends.neuron.geometry import build_morphology_geometry
from compneurovis.backends.neuron.io import load_swc_neuron
from compneurovis.backends.neuron.section_names import public_section_name
from compneurovis.core.runtime.performance import perf_log
from neuron import h

from sphere_brush import MorphologySphereActionBrush

# This example is currently a diagnostic target for live morphology retargeting.
# Respect an explicit user path; otherwise keep its structured logs local.
PERF_LOG_DIR = Path.cwd() / ".compneurovis" / "perf-logs" / "morphology-paint"
os.environ.setdefault("COMPNV_PERF_LOG", str(PERF_LOG_DIR))


DT = 0.3
DISPLAY_DT = DT
V_INIT = -65.0
DEFAULT_GNABAR = 0.12
params = {"dt": DT}


@dataclass(frozen=True, slots=True)
class MorphologyDisplay:
    data: object
    unit: str | None
    color_limits: tuple[float, float]
    color_map: str


@dataclass(frozen=True, slots=True)
class PaintTarget:
    attribute: str
    scope: str
    min: float
    max: float
    default: float
    unit: str
    display_source: object
    color_map: str


LIVE_DISPLAYS = {
    "Voltage": MorphologyDisplay(
        "v", "mV", (-80.0, 50.0), "ramp:#3366CC:#CC3311"
    ),
    "m gate": MorphologyDisplay(
        "m_hh", None, (0.0, 1.0), "ramp:#CC0066:#00CC66"
    ),
    "h gate": MorphologyDisplay(
        "h_hh", None, (0.0, 1.0), "ramp:#E19941:#4169E1"
    ),
    "n gate": MorphologyDisplay(
        "n_hh", None, (0.0, 1.0), "ramp:#0047E6:#E69F00"
    ),
}


def load_sections() -> list:
    repo_root = Path(__file__).resolve().parents[4]
    swc_path = repo_root / "res" / "Animal_2_Basal_2.CNG.swc"
    if not swc_path.is_file():
        raise FileNotFoundError(f"SWC file not found: {swc_path}")
    return load_swc_neuron(str(swc_path))


def configure_cell(sections: list) -> list:
    for section in sections:
        section.insert("hh")
        if "soma" not in section.name().lower():
            section.nseg = 10
        section.cm = 1.0
        section.Ra = 35.4
        for segment in section:
            segment.gnabar_hh = DEFAULT_GNABAR
            segment.gkbar_hh = 0.036
            segment.gl_hh = 0.0003
            segment.el_hh = -54.3

    somas = [section for section in sections if "soma" in section.name().lower()]
    if not somas:
        raise RuntimeError("No soma sections found for stimulation")
    clamps = []
    for soma in somas:
        for pulse_index in range(20):
            clamp = h.IClamp(soma(0.5))
            clamp.delay = 2.0 + pulse_index * 20.0
            clamp.dur = 5.0
            clamp.amp = 1.0
            clamps.append(clamp)
    return clamps


sections = load_sections()
clamps = configure_cell(sections)  # Retain the point processes for the live run.
h.dt = DT
h.celsius = 6.3
h.finitialize(V_INIT)

# The same concrete geometry establishes the app-local intersection/index map.
# The NEURON source independently publishes its ordinary morphology GeometrySpec.
geometry = build_morphology_geometry(sections)
sections_by_name = {
    public_section_name(section.name()): section for section in sections
}
paint_segments = tuple(
    sections_by_name[section_name](float(xloc))
    for section_name, xloc in zip(geometry.section_names, geometry.xlocs)
)
paint_sections = tuple(
    sections_by_name[section_name] for section_name in geometry.section_names
)
visual_indices_by_section: dict[str, list[int]] = {}
for visual_index, section_name in enumerate(geometry.section_names):
    visual_indices_by_section.setdefault(str(section_name), []).append(visual_index)
ra_display_values = np.asarray(
    [float(section.Ra) for section in paint_sections], dtype=np.float32
)
PAINT_TARGETS = {
    "Na conductance": PaintTarget(
        "gnabar_hh",
        "segment",
        0.0,
        0.30,
        DEFAULT_GNABAR,
        "S/cm^2",
        "gnabar_hh",
        "ramp:#28105E:#FFE04B",
    ),
    "K conductance": PaintTarget(
        "gkbar_hh",
        "segment",
        0.0,
        0.12,
        0.036,
        "S/cm^2",
        "gkbar_hh",
        "ramp:#0047A8:#FF6B00",
    ),
    "Membrane capacitance": PaintTarget(
        "cm",
        "segment",
        0.2,
        3.0,
        1.0,
        "uF/cm^2",
        "cm",
        "ramp:#006D5B:#F05AA6",
    ),
    "Axial resistance": PaintTarget(
        "Ra",
        "section",
        20.0,
        200.0,
        35.4,
        "ohm cm",
        ra_display_values,
        "ramp:#263238:#29B6F6",
    ),
}
stroke_state = {"target": None, "owners": {}}


def selected_paint_value(ctx) -> float:
    target_name = str(ctx.get_value(paint_target, "Na conductance"))
    target = PAINT_TARGETS[target_name]
    return float(ctx.get_value(paint_value_controls[target_name], target.default))


def paint_spatial_parameter(ctx, indices, value: float) -> None:
    target_name = str(ctx.get_value(paint_target, "Na conductance"))
    target = PAINT_TARGETS[target_name]
    if stroke_state["target"] != target_name:
        stroke_state["target"] = target_name
        stroke_state["owners"].clear()

    for index in indices:
        resolved_index = int(index)
        section_name = str(geometry.section_names[resolved_index])
        if target.scope == "section":
            owner = paint_sections[resolved_index]
            owner_key = ("section", section_name)
        else:
            owner = paint_segments[resolved_index]
            owner_key = (
                "segment",
                section_name,
                round(float(owner.x), 9),
            )
        stroke_state["owners"].setdefault(
            owner_key,
            (owner, float(getattr(owner, target.attribute))),
        )
        setattr(owner, target.attribute, float(value))
        if isinstance(target.display_source, np.ndarray):
            affected = (
                visual_indices_by_section[section_name]
                if target.scope == "section"
                else (resolved_index,)
            )
            target.display_source[affected] = float(value)


def log_parameter_stroke(_ctx, indices, value: float) -> None:
    resolved_indices = [int(index) for index in indices]
    target_name = str(stroke_state["target"])
    target = PAINT_TARGETS[target_name]
    owners = list(stroke_state["owners"].values())
    before = [before_value for _owner, before_value in owners]
    after = [float(getattr(owner, target.attribute)) for owner, _before in owners]
    changed = sum(
        abs(before_value - after_value) > 1e-12
        for before_value, after_value in zip(before, after)
    )
    print(
        "[spatial-paint] stroke complete",
        f"t_ms={float(h.t):.3f}",
        f"target={target_name!r}",
        f"attribute={target.attribute}",
        f"visual_segments={len(resolved_indices)}",
        f"model_owners={len(owners)}",
        f"changed={changed}",
        f"requested={value:.4f}",
        f"before=({min(before):.4f}, {max(before):.4f})",
        f"neuron_after=({min(after):.4f}, {max(after):.4f})",
        flush=True,
    )
    stroke_state["target"] = None
    stroke_state["owners"].clear()


def set_sim_dt(ctx, value: float) -> None:
    params["dt"] = float(value)
    ctx.backend.dt = params["dt"]
    h.dt = params["dt"]


def reset_sim(ctx) -> None:
    ctx.reset()


def remember_live_display(ctx, value: str) -> None:
    name = str(value)
    perf_log("morphology_paint_demo", "live_display_selected", variable=name)
    apply_morphology_display(name, LIVE_DISPLAYS[name])
    ctx.set_value(saved_live_display, name)


def apply_morphology_display(name: str, display: MorphologyDisplay) -> None:
    morphology.set_display(
        name=name,
        data=display.data,
        unit=display.unit,
        color_limits=display.color_limits,
        color_map=display.color_map,
    )


def paint_display(name: str) -> MorphologyDisplay:
    target = PAINT_TARGETS[name]
    return MorphologyDisplay(
        target.display_source,
        target.unit,
        (target.min, target.max),
        target.color_map,
    )


def set_workflow_mode(ctx, value: str) -> None:
    painting = str(value) == "Paint"
    target_name = str(ctx.get_value(paint_target, "Na conductance"))
    perf_log(
        "morphology_paint_demo",
        "workflow_mode_selected",
        mode=str(value),
        paint_target=target_name,
    )
    display_variable.visible = not painting
    paint_target.visible = painting
    brush_radius.visible = painting
    for name, control in paint_value_controls.items():
        control.visible = painting and name == target_name
    if painting:
        apply_morphology_display(target_name, paint_display(target_name))
    else:
        live_name = str(ctx.get_value(saved_live_display, "Voltage"))
        apply_morphology_display(live_name, LIVE_DISPLAYS[live_name])
    ctx.set_value(paint_enabled, painting)


def set_paint_target(ctx, value: str) -> None:
    target_name = str(value)
    painting = str(ctx.get_value(workflow_mode, "Live view")) == "Paint"
    perf_log(
        "morphology_paint_demo",
        "paint_target_selected",
        target=target_name,
        painting=painting,
    )
    for name, control in paint_value_controls.items():
        control.visible = painting and name == target_name
    if painting:
        apply_morphology_display(target_name, paint_display(target_name))


src = cnv.neuron.source(
    sections=sections,
    dt=DT,
    display_dt=DISPLAY_DT,
    v_init=V_INIT,
    title="Live spatial conductance painting",
)

paint_enabled = src.create_value("paint enabled", initial=False)
saved_live_display = src.create_value("saved live display", initial="Voltage")

src.slider(
    "dt",
    label="Simulation dt (ms)",
    get=lambda: params["dt"],
    set=set_sim_dt,
    min=0.025,
    max=0.5,
)
workflow_mode = src.dropdown(
    "workflow mode",
    label="Mode",
    options=("Live view", "Paint"),
    default="Live view",
    set=set_workflow_mode,
)
display_variable = src.dropdown(
    "display variable",
    label="Displayed morphology variable",
    options=tuple(LIVE_DISPLAYS),
    default="Voltage",
    set=remember_live_display,
)
paint_target = src.dropdown(
    "paint target",
    label="Paint target",
    options=tuple(PAINT_TARGETS),
    default="Na conductance",
    set=set_paint_target,
    visible=False,
)
paint_value_controls = {
    name: src.slider(
        f"{name} brush value",
        label=f"{name} paint value ({target.unit})",
        min=target.min,
        max=target.max,
        default=target.default,
        steps=150,
        send_to_backend=True,
        visible=False,
    )
    for name, target in PAINT_TARGETS.items()
}
brush_radius = src.slider(
    "sphere brush radius",
    label="Brush radius (um)",
    min=0.25,
    max=30.0,
    default=5.0,
    steps=119,
    send_to_backend=True,
    visible=False,
)

morphology = src.morphology(
    name="Live morphology",
    variable=LIVE_DISPLAYS["Voltage"].data,
    unit=LIVE_DISPLAYS["Voltage"].unit,
    color_limits=LIVE_DISPLAYS["Voltage"].color_limits,
    color_map=LIVE_DISPLAYS["Voltage"].color_map,
    selectable=False,
)
src.add(
    MorphologySphereActionBrush(
        morphology=morphology,
        geometry=geometry,
        brush_value=selected_paint_value,
        brush_radius=brush_radius,
        enabled=paint_enabled,
        apply=paint_spatial_parameter,
        finish=log_parameter_stroke,
    )
)
src.button("reset", label="Reset", fn=reset_sim)

cnv.layout(((morphology,), (src.controls_panel,)))
cnv.show(title="Live spatial conductance painting")
