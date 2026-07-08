"""Multi-cell Jaxley visualizer using source-level inline authoring.

Requires: jax, jaxley
Run: python examples/jaxley/multicell_example.py
"""

from __future__ import annotations

import numpy as np

import jaxley as jx
from jaxley.channels import HH
from jaxley.connect import connect
from jaxley.synapses import IonotropicSynapse

import compneurovis as cnv
from compneurovis.backends.jaxley.utils import translate_cells_xyzr


params = {
    "display_dt": 50.0,
    "stim_amp": 0.5,
    "stim_dur": 5.0,
    "syn_gs": 5e-4,
    "syn_e_syn": 0.0,
    "syn_k_minus": 0.5,
    "syn_v_th": -35.0,
    "syn_delta": 10.0,
    "hh_gna": 0.12,
    "hh_gk": 0.036,
    "hh_gleak": 3e-4,
}


def make_straight_cell(name: str):
    comp = jx.Compartment()
    branches = [jx.Branch(comp, ncomp=4), jx.Branch(comp, ncomp=8), jx.Branch(comp, ncomp=10)]
    xyzr = [
        np.array([[0.0, 0.0, 0.0, 10.0], [18.0, 0.0, 0.0, 10.0]], dtype=np.float32),
        np.array([[18.0, 0.0, 0.0, 2.0], [120.0, 28.0, 0.0, 2.0]], dtype=np.float32),
        np.array([[0.0, 0.0, 0.0, 1.2], [-150.0, 0.0, 0.0, 1.2]], dtype=np.float32),
    ]
    cell = jx.Cell(branches, parents=[-1, 0, 0], xyzr=xyzr)
    cell.meta_name = name
    return cell


def make_y_cell(name: str):
    comp = jx.Compartment()
    branches = [jx.Branch(comp, ncomp=4), jx.Branch(comp, ncomp=7), jx.Branch(comp, ncomp=7), jx.Branch(comp, ncomp=10)]
    xyzr = [
        np.array([[0.0, 0.0, 0.0, 8.0], [16.0, 0.0, 0.0, 8.0]], dtype=np.float32),
        np.array([[16.0, 0.0, 0.0, 2.2], [88.0, 44.0, 0.0, 2.2]], dtype=np.float32),
        np.array([[16.0, 0.0, 0.0, 2.2], [88.0, -44.0, 0.0, 2.2]], dtype=np.float32),
        np.array([[0.0, 0.0, 0.0, 1.0], [-140.0, 0.0, 0.0, 1.0]], dtype=np.float32),
    ]
    cell = jx.Cell(branches, parents=[-1, 0, 0, 0], xyzr=xyzr)
    cell.meta_name = name
    return cell


def make_branching_cell(name: str):
    comp = jx.Compartment()
    branches = [
        jx.Branch(comp, ncomp=4),
        jx.Branch(comp, ncomp=6),
        jx.Branch(comp, ncomp=5),
        jx.Branch(comp, ncomp=5),
        jx.Branch(comp, ncomp=4),
        jx.Branch(comp, ncomp=4),
        jx.Branch(comp, ncomp=9),
    ]
    xyzr = [
        np.array([[0.0, 0.0, 0.0, 9.0], [18.0, 0.0, 0.0, 9.0]], dtype=np.float32),
        np.array([[18.0, 0.0, 0.0, 3.0], [70.0, 18.0, 0.0, 3.0]], dtype=np.float32),
        np.array([[70.0, 18.0, 0.0, 2.0], [120.0, 52.0, 0.0, 2.0]], dtype=np.float32),
        np.array([[70.0, 18.0, 0.0, 2.0], [120.0, -10.0, 0.0, 2.0]], dtype=np.float32),
        np.array([[120.0, -10.0, 0.0, 1.2], [150.0, 18.0, 0.0, 1.2]], dtype=np.float32),
        np.array([[120.0, -10.0, 0.0, 1.2], [150.0, -34.0, 0.0, 1.2]], dtype=np.float32),
        np.array([[0.0, 0.0, 0.0, 1.0], [-120.0, -8.0, 0.0, 1.0]], dtype=np.float32),
    ]
    cell = jx.Cell(branches, parents=[-1, 0, 1, 1, 3, 3, 0], xyzr=xyzr)
    cell.meta_name = name
    return cell


cells = [make_straight_cell("cell1"), make_y_cell("cell2"), make_branching_cell("cell3")]
translate_cells_xyzr(cells, offsets=[(0.0, 0.0, 0.0), (220.0, 120.0, 0.0), (440.0, -40.0, 0.0)])


def pulse_schedule():
    return [
        (2.0, params["stim_dur"], params["stim_amp"]),
        (20.0, params["stim_dur"], params["stim_amp"]),
        (40.0, params["stim_dur"], params["stim_amp"]),
        (60.0, params["stim_dur"], params["stim_amp"]),
        (80.0, params["stim_dur"], params["stim_amp"]),
    ]


def apply_hh_parameters(network):
    network.set("HH_gNa", params["hh_gna"])
    network.set("HH_gK", params["hh_gk"])
    network.set("HH_gLeak", params["hh_gleak"])


def apply_synapse_parameters(network):
    edge_view = network.select(edges="all")
    edge_view.set("IonotropicSynapse_gS", params["syn_gs"])
    edge_view.set("IonotropicSynapse_e_syn", params["syn_e_syn"])
    edge_view.set("IonotropicSynapse_k_minus", params["syn_k_minus"])
    edge_view.set("IonotropicSynapse_v_th", params["syn_v_th"])
    edge_view.set("IonotropicSynapse_delta", params["syn_delta"])


def rebuild_stimulus(network, dt: float):
    network.delete_stimuli()
    pulses = pulse_schedule()
    t_max = pulses[-1][0] + pulses[-1][1] + 10.0
    current = sum(
        jx.step_current(i_delay=delay, i_dur=dur, i_amp=amp, delta_t=dt, t_max=t_max)
        for delay, dur, amp in pulses
    )
    network.cell(0).branch(0).loc(0.5).stimulate(current)


def setup(network, _cells):
    network.insert(HH())
    apply_hh_parameters(network)
    connect(network.cell(0).branch(2).comp(9), network.cell(1).branch(0).comp(1), IonotropicSynapse())
    connect(network.cell(1).branch(3).comp(9), network.cell(2).branch(0).comp(1), IonotropicSynapse())
    connect(network.cell(2).branch(6).comp(8), network.cell(0).branch(1).comp(4), IonotropicSynapse())
    apply_synapse_parameters(network)
    network.select(edges="all").set("IonotropicSynapse_s", 0.0)
    rebuild_stimulus(network, dt=0.1)
    return {"stimulus": network.externals.get("i")}


src = cnv.jaxley.source(cells=cells, setup=setup, dt=0.1, v_init=-70.0, display_dt=params["display_dt"])
morph = src.morphology(color_limits=(-80.0, 50.0))
history = src.history(title="Selected voltage", y_unit="mV", rolling_window=500.0)
cnv.layout(((morph, history), (src.controls_panel,)))


def slider(name: str, label: str, min_value: float, max_value: float, steps: int, *, scale: str = "linear", refresh_params: bool = False, refresh_externals: bool = False, setter=None):
    src.control(
        name,
        label=label,
        get=lambda name=name: params[name],
        set=setter or (lambda ctx, value, name=name: params.__setitem__(name, float(value))),
        min=min_value,
        max=max_value,
        presentation=cnv.ControlPresentationSpec(kind="slider", steps=steps, scale=scale),
        refresh_params=refresh_params,
        refresh_externals=refresh_externals,
    )


def set_display_dt(ctx, value):
    params["display_dt"] = max(0.1, float(value))
    ctx.backend.display_dt = params["display_dt"]


def set_stim_param(name: str):
    def setter(ctx, value):
        params[name] = float(value)
        if ctx.backend.network is not None:
            rebuild_stimulus(ctx.backend.network, dt=ctx.backend.dt)
    return setter


def set_syn_param(name: str):
    def setter(ctx, value):
        params[name] = float(value)
        if ctx.backend.network is not None:
            apply_synapse_parameters(ctx.backend.network)
    return setter


def set_hh_param(name: str):
    def setter(ctx, value):
        params[name] = float(value)
        if ctx.backend.network is not None:
            apply_hh_parameters(ctx.backend.network)
    return setter


slider("display_dt", "Visual update interval (ms sim/update)", 0.1, 50.0, 200, setter=set_display_dt)
slider("stim_amp", "Stimulus amplitude (nA)", 0.0, 5.0, 200, refresh_externals=True, setter=set_stim_param("stim_amp"))
slider("stim_dur", "Stimulus duration (ms)", 1.0, 20.0, 190, refresh_externals=True, setter=set_stim_param("stim_dur"))
slider("syn_gs", "Synapse gS", 1e-5, 1e-1, 200, scale="log", refresh_params=True, setter=set_syn_param("syn_gs"))
slider("syn_e_syn", "Synapse reversal (mV)", -80.0, 60.0, 280, refresh_params=True, setter=set_syn_param("syn_e_syn"))
slider("syn_k_minus", "Synapse k_minus", 1e-3, 1.0, 200, scale="log", refresh_params=True, setter=set_syn_param("syn_k_minus"))
slider("syn_v_th", "Synapse pre-V threshold (mV)", -70.0, 10.0, 160, refresh_params=True, setter=set_syn_param("syn_v_th"))
slider("syn_delta", "Synapse pre-V slope (mV)", 1.0, 20.0, 190, refresh_params=True, setter=set_syn_param("syn_delta"))
slider("hh_gna", "HH gNa (S/cm^2)", 0.01, 0.3, 200, refresh_params=True, setter=set_hh_param("hh_gna"))
slider("hh_gk", "HH gK (S/cm^2)", 0.005, 0.12, 200, refresh_params=True, setter=set_hh_param("hh_gk"))
slider("hh_gleak", "HH gLeak (S/cm^2)", 1e-5, 3e-3, 200, scale="log", refresh_params=True, setter=set_hh_param("hh_gleak"))

cnv.show(title="Multi-cell Jaxley viewer")

