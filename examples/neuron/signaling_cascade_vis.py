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

def set_external_input(value: float) -> None:
    ligand.external_input = float(value)


def set_decay_rate(value: float) -> None:
    ligand.decay_rate = float(value)


def set_kd1(value: float) -> None:
    receptor.kd1 = float(value)


def set_efficacy1(value: float) -> None:
    receptor.efficacy1 = float(value)


def set_decay1(value: float) -> None:
    receptor.decay1 = float(value)


def set_capacity(value: float) -> None:
    receptor.capacity = float(value)


def set_baseline_activity(value: float) -> None:
    receptor.baseline_activity = float(value)


def set_s_min(value: float) -> None:
    effector.s_min = float(value)


def set_s_max(value: float) -> None:
    effector.s_max = float(value)


def set_k(value: float) -> None:
    effector.K = float(value)


def set_n(value: float) -> None:
    effector.n = int(round(float(value)))


def set_tau_on(value: float) -> None:
    effector.tau_on = float(value)


def set_tau_off(value: float) -> None:
    effector.tau_off = float(value)


control_specs = (
    ("external_input", "external input", lambda: ligand.external_input, set_external_input, 0.005, 0.0, 0.1, 200, "linear", "float"),
    ("decay_rate", "decay rate", lambda: ligand.decay_rate, set_decay_rate, 0.00955, 1e-5, 0.1, 200, "log", "float"),
    ("kd1", "kd1", lambda: receptor.kd1, set_kd1, 3.09, 0.01, 10.0, 200, "log", "float"),
    ("efficacy1", "efficacy1", lambda: receptor.efficacy1, set_efficacy1, 1.0, 0.0, 2.0, 200, "linear", "float"),
    ("decay1", "decay1", lambda: receptor.decay1, set_decay1, 0.275, 0.0001, 1.0, 200, "log", "float"),
    ("capacity", "capacity", lambda: receptor.capacity, set_capacity, 1.62, 0.0, 5.0, 200, "linear", "float"),
    ("baseline_activity", "baseline activity", lambda: receptor.baseline_activity, set_baseline_activity, 0.0, 0.0, 1.0, 200, "linear", "float"),
    ("s_min", "s min", lambda: effector.s_min, set_s_min, 0.0, 0.0, 1.0, 100, "linear", "float"),
    ("s_max", "s max", lambda: effector.s_max, set_s_max, 1.0, 0.0, 2.0, 100, "linear", "float"),
    ("K", "K", lambda: effector.K, set_k, 0.5, 0.001, 10.0, 200, "log", "float"),
    ("n", "n", lambda: effector.n, set_n, 3, 1, 6, 5, "linear", "int"),
    ("tau_on", "tau on", lambda: effector.tau_on, set_tau_on, 151.0, 1.0, 200.0, 200, "linear", "float"),
    ("tau_off", "tau off", lambda: effector.tau_off, set_tau_off, 140.0, 1.0, 200.0, 200, "linear", "float"),
)

for _name, _label, _get_value, set_value, default, *_rest in control_specs:
    set_value(default)
src = cnv.neuron.source(sections=[soma], dt=DEFAULT_DT, display_dt=DEFAULT_DISPLAY_DT)
cascade_data = src.record_refs(
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
    window=20.0,
)
cascade = src.line(
    "Signaling cascade",
    source=cascade_data,
    rolling_window=20.0,
    y_label="Signal",
    y_min=0.0,
    y_max=1.8,
    colors={
        "Ligand C (uM)": (100, 200, 255),
        "Receptor bound1": (255, 100, 100),
        "Receptor occupancy": (100, 255, 100),
        "Receptor activation": (200, 100, 255),
        "Effector s": (255, 165, 0),
        "Effector s_inf": (0, 0, 0),
    },
    max_refresh_hz=60.0,
)

for name, label, get_value, set_value, default, min_value, max_value, steps, scale, value_type in control_specs:
    src.slider(
        name,
        label=label,
        get=get_value,
        set=lambda ctx, value, set_value=set_value: set_value(value),
        default=default,
        min=min_value,
        max=max_value,
        steps=steps,
        scale=scale,
        int=value_type == "int",
    )

cnv.layout(((cascade, src.controls_panel),))

cnv.show(title="Signaling cascade viewer")
