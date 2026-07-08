"""scratch/hh_neuron_inline.py — single-compartment HH model using compneurovis.inline sugar API.

NEURON runs in the backend subprocess; Qt frontend stays in the main process.
No if __name__ == '__main__' required.

Requires: NEURON
Run: python scratch/hh_neuron_inline.py
"""
from neuron import h
import compneurovis as cnv

# Single HH point compartment
soma = h.Section(name="soma")
soma.L = 12.6157
soma.diam = 12.6157
soma.nseg = 1
soma.insert("hh")
seg = soma(0.5)

clamp = h.IClamp(seg)
clamp.delay = 0.0
clamp.dur = 1e9
clamp.amp = 0.1   # nA — supra-threshold, produces tonic spiking

h.dt = 0.025
h.celsius = 6.3
h.finitialize(-65.0)


def _advance(ctx):
    for _ in range(100):
        h.fadvance()
        ctx.trace_sampler.sample()


sim = cnv.source(_advance)

sim.trace("Voltage",
          read=lambda: float(seg.v),
          x=lambda: float(h.t),
          y_min=-90.0, y_max=60.0, y_unit="mV",
          rolling_window=80.0, max_samples=4000)

sim.trace("HH gates",
          read={"m": lambda: float(seg.m_hh),
                "h": lambda: float(seg.h_hh),
                "n": lambda: float(seg.n_hh)},
          x=lambda: float(h.t),
          y_min=-0.05, y_max=1.05,
          rolling_window=80.0, max_samples=4000)

sim.control("clamp_amp", label="IClamp amplitude (nA)",
            get=lambda: float(clamp.amp),
            set=lambda ctx, v: setattr(clamp, "amp", float(v)),
            min=-0.2, max=0.5)

sim.action("reset", label="Reset",
           fn=lambda ctx: h.finitialize(-65.0), resets_fields=True)

cnv.show()
