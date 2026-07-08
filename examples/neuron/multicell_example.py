"""Multi-cell NEURON network visualizer using source-level inline authoring.

Requires: NEURON
Run: python examples/neuron/multicell_example.py
"""

from __future__ import annotations

import time

from neuron import h

import compneurovis as cnv
from compneurovis.backends.neuron.utils import generate_layout


def make_straight_cell(name):
    soma = h.Section(name=f"{name}_soma")
    soma.L = 20
    soma.diam = 20
    soma.nseg = 1
    dend = h.Section(name=f"{name}_dend")
    dend.L = 200
    dend.diam = 3
    dend.nseg = 10
    dend.connect(soma(1))
    axon = h.Section(name=f"{name}_axon")
    axon.L = 300
    axon.diam = 1.5
    axon.nseg = 10
    axon.connect(soma(0))
    return [soma, dend, axon]


def make_y_cell(name):
    soma = h.Section(name=f"{name}_soma")
    soma.L = 25
    soma.diam = 15
    soma.nseg = 1
    dend_a = h.Section(name=f"{name}_dend_a")
    dend_a.L = 150
    dend_a.diam = 2.5
    dend_a.nseg = 10
    dend_a.connect(soma(1))
    dend_b = h.Section(name=f"{name}_dend_b")
    dend_b.L = 180
    dend_b.diam = 2.5
    dend_b.nseg = 10
    dend_b.connect(soma(1))
    axon = h.Section(name=f"{name}_axon")
    axon.L = 250
    axon.diam = 1.0
    axon.nseg = 10
    axon.connect(soma(0))
    return [soma, dend_a, dend_b, axon]


def make_branching_cell(name):
    soma = h.Section(name=f"{name}_soma")
    soma.L = 30
    soma.diam = 18
    soma.nseg = 1
    dend = h.Section(name=f"{name}_dend")
    dend.L = 120
    dend.diam = 4
    dend.nseg = 10
    dend.connect(soma(1))
    branch_a = h.Section(name=f"{name}_branch_a")
    branch_a.L = 100
    branch_a.diam = 2.5
    branch_a.nseg = 10
    branch_a.connect(dend(1))
    branch_b = h.Section(name=f"{name}_branch_b")
    branch_b.L = 80
    branch_b.diam = 2.5
    branch_b.nseg = 10
    branch_b.connect(dend(1))
    twig_a = h.Section(name=f"{name}_twig_a")
    twig_a.L = 60
    twig_a.diam = 1.5
    twig_a.nseg = 5
    twig_a.connect(branch_b(1))
    twig_b = h.Section(name=f"{name}_twig_b")
    twig_b.L = 50
    twig_b.diam = 1.5
    twig_b.nseg = 5
    twig_b.connect(branch_b(1))
    axon = h.Section(name=f"{name}_axon")
    axon.L = 200
    axon.diam = 1.2
    axon.nseg = 10
    axon.connect(soma(0))
    return [soma, dend, branch_a, branch_b, twig_a, twig_b, axon]


t0 = time.perf_counter()
cell1_secs = make_straight_cell("cell1")
cell2_secs = make_y_cell("cell2")
cell3_secs = make_branching_cell("cell3")
sections = cell1_secs + cell2_secs + cell3_secs
print(f"Cells built in {time.perf_counter() - t0:.2f}s")
for sec in sections:
    sec.insert("hh")

syn1 = h.ExpSyn(cell2_secs[0](0.5))
syn1.tau = 2.0
syn1.e = 0.0
nc1 = h.NetCon(cell1_secs[2](0.9)._ref_v, syn1, sec=cell1_secs[2])
nc1.weight[0] = 0.05
nc1.delay = 1.0
syn2 = h.ExpSyn(cell3_secs[0](0.5))
syn2.tau = 2.0
syn2.e = 0.0
nc2 = h.NetCon(cell2_secs[3](0.9)._ref_v, syn2, sec=cell2_secs[3])
nc2.weight[0] = 0.05
nc2.delay = 1.0
syn3 = h.ExpSyn(cell1_secs[1](0.5))
syn3.tau = 2.0
syn3.e = 0.0
nc3 = h.NetCon(cell3_secs[6](0.9)._ref_v, syn3, sec=cell3_secs[6])
nc3.weight[0] = 0.03
nc3.delay = 1.0

iclamps = []
for delay, dur, amp in [(2, 5, 0.5), (20, 5, 0.5), (40, 5, 0.5), (60, 5, 0.5), (80, 5, 0.5)]:
    clamp = h.IClamp(cell1_secs[0](0.5))
    clamp.delay = delay
    clamp.dur = dur
    clamp.amp = amp
    iclamps.append(clamp)

generate_layout(
    sections,
    cell_connections=[
        (cell2_secs[0], cell1_secs[2], 1.0),
        (cell3_secs[0], cell2_secs[3], 1.0),
    ],
)

src = cnv.neuron.source(sections=sections, dt=0.025, display_dt=0.25)
morph = src.morphology(variable="v", name="Voltage", unit="mV", color_limits=(-80.0, 50.0), selected="cell1_soma@0.50000")
volt = src.line("Selected voltage", source=morph.selection, y_label="Voltage", y_unit="mV", rolling_window=120.0, y_min=-85.0, y_max=55.0)

cnv.layout(((morph, volt),))

cnv.show(title="Multi-cell network viewer")
