"""Signaling cascade point-process viewer using source-level inline authoring.

Requires: NEURON and compiled mechanisms under examples/neuron/signaling_cascade_mod/
Run: python examples/neuron/signaling_cascade_vis.py
"""

from __future__ import annotations

from pathlib import Path

from neuron import h, load_mechanisms

import compneurovis as cnv


h.load_file("stdrun.hoc")
MECHANISM_DIR = Path(__file__).with_name("signaling_cascade_mod")
DEFAULT_DT = 0.01
DEFAULT_DISPLAY_DT = 1.0

if not load_mechanisms(str(MECHANISM_DIR), warn_if_already_loaded=False):
    raise RuntimeError(
        "Bundled NEURON mechanisms are not compiled. Compile the .mod files in "
        f"{MECHANISM_DIR} before running this example."
    )

soma = h.Section(name="soma")
soma.L = 20.0
soma.diam = 20.0
soma.nseg = 1
soma.Ra = 150.0
soma.cm = 1.0
soma.insert("pas")
for seg in soma:
    seg.pas.g = 1e-4
    seg.pas.e = -65.0

ligand = h.GenericLigand(soma(0.5))
ligand.C_init = 0.0
receptor = h.GenericReceptor(soma(0.5))
receptor.n_ligands = 1
h.setpointer(ligand._ref_C, "C_lig1", receptor)
h.setpointer(ligand._ref_C_init, "C_lig2", receptor)
h.setpointer(ligand._ref_C_init, "C_lig3", receptor)
h.setpointer(ligand._ref_C_init, "C_lig4", receptor)
effector = h.SetpointRelaxEffector(soma(0.5))
effector.K = 0.5
h.setpointer(receptor._ref_activation, "drive", effector)

control_targets = {
    "external_input": (ligand, "external_input", 0.005, 0.0, 0.1, 200, "linear"),
    "decay_rate": (ligand, "decay_rate", 0.00955, 1e-5, 0.1, 200, "log"),
    "kd1": (receptor, "kd1", 3.09, 0.01, 10.0, 200, "log"),
    "efficacy1": (receptor, "efficacy1", 1.0, 0.0, 2.0, 200, "linear"),
    "decay1": (receptor, "decay1", 0.275, 0.0001, 1.0, 200, "log"),
    "capacity": (receptor, "capacity", 1.62, 0.0, 5.0, 200, "linear"),
    "baseline_activity": (receptor, "baseline_activity", 0.0, 0.0, 1.0, 200, "linear"),
    "s_min": (effector, "s_min", 0.0, 0.0, 1.0, 100, "linear"),
    "s_max": (effector, "s_max", 1.0, 0.0, 2.0, 100, "linear"),
    "K": (effector, "K", 0.5, 0.001, 10.0, 200, "log"),
    "n": (effector, "n", 3, 1, 6, 5, "linear"),
    "tau_on": (effector, "tau_on", 151.0, 1.0, 200.0, 200, "linear"),
    "tau_off": (effector, "tau_off", 140.0, 1.0, 200.0, 200, "linear"),
}
for _name, (obj, attr, default, *_rest) in control_targets.items():
    setattr(obj, attr, default)

src = cnv.neuron.source(sections=[soma], dt=DEFAULT_DT, display_dt=DEFAULT_DISPLAY_DT)
cascade = src.line_refs(
    "Signaling cascade",
    refs=(
        ligand._ref_C,
        receptor._ref_bound1,
        receptor._ref_occupancy,
        receptor._ref_activation,
        effector._ref_s,
        effector._ref_s_inf,
    ),
    series=("Ligand C (uM)", "Receptor bound1", "Receptor occupancy", "Receptor activation", "Effector s", "Effector s_inf"),
    unit="a.u.",
    rolling_window=20.0,
    y_label="Signal",
    y_min=0.0,
    y_max=1.8,
    series_colors={
        "Ligand C (uM)": (100, 200, 255),
        "Receptor bound1": (255, 100, 100),
        "Receptor occupancy": (100, 255, 100),
        "Receptor activation": (200, 100, 255),
        "Effector s": (255, 165, 0),
        "Effector s_inf": (0, 0, 0),
    },
    max_refresh_hz=60.0,
)

for name, (obj, attr, default, min_value, max_value, steps, scale) in control_targets.items():
    is_int = name == "n"
    src.control(
        name,
        label=name.replace("_", " "),
        get=lambda obj=obj, attr=attr: getattr(obj, attr),
        set=lambda ctx, value, obj=obj, attr=attr, is_int=is_int: setattr(obj, attr, int(round(float(value))) if is_int else float(value)),
        value_spec=cnv.ScalarValueSpec(default=default, min=min_value, max=max_value, value_type="int" if is_int else "float"),
        presentation=cnv.ControlPresentationSpec(kind="slider", steps=steps, scale=scale),
    )

cnv.layout(((cascade, src.controls_panel),))

cnv.show(title="Signaling cascade viewer")
