# CompNeuroVis

CompNeuroVis connects computational neuroscience simulations and data to
interactive desktop visualizations. Sources expose model data and controls;
views opt into line plots, morphology, surfaces, and other panels; cnv.show()
integrates those pieces into one application.

## Alpha Status

CompNeuroVis 0.4.0a1 is an alpha release. All versions before 1.0.0 are unstable
prereleases. Public APIs may change between releases.

This release supports the inline source workflow used by current examples.
Notebook, distributed, and multi-source composition paths remain experimental.

## Installation

CompNeuroVis requires Python 3.11.

Install the alpha release:

~~~bash
pip install --pre compneurovis
~~~

Install current checkout:

~~~bash
pip install -e .
~~~

Install optional simulator integrations:

~~~bash
pip install -e ".[neuron]"
pip install -e ".[jaxley]"
~~~

Notebook dependencies are experimental:

~~~bash
pip install -e ".[notebook]"
~~~

## Minimal App

~~~python
import math

import compneurovis as cnv


state = {"time_ms": 0.0, "frequency_hz": 1.0}


def step(ctx):
    state["time_ms"] += 16.0


def set_frequency(ctx, value):
    state["frequency_hz"] = float(value)


src = cnv.source(step)

wave = src.line(
    "Sine wave",
    read=lambda: math.sin(
        2.0
        * math.pi
        * state["frequency_hz"]
        * state["time_ms"]
        / 1000.0
    ),
    x=lambda: state["time_ms"],
    y_min=-1.1,
    y_max=1.1,
)

src.slider(
    "frequency_hz",
    label="Frequency (Hz)",
    get=lambda: state["frequency_hz"],
    set=set_frequency,
    min=0.1,
    max=5.0,
)

cnv.layout(((wave,), (src.controls_panel,)))
cnv.show(title="Sine wave")
~~~

Run repository version:

~~~bash
python examples/custom/sine_wave.py
~~~

## NEURON Morphology

NEURON sources keep simulator-specific data collection optimized while using
the same line, control, layout, and show API.

~~~python
from neuron import h

import compneurovis as cnv


soma = h.Section(name="soma")
soma.L = soma.diam = 20.0
soma.insert("hh")

stim = h.IClamp(soma(0.5))
stim.delay = 100.0
stim.dur = 5.0
stim.amp = 0.8


def set_stimulus(ctx, value):
    stim.amp = float(value)


src = cnv.neuron.source(
    sections=[soma],
    dt=0.025,
    display_dt=0.5,
)

morphology = src.morphology(
    variable="v",
    name="Membrane voltage",
    unit="mV",
    color_limits=(-80.0, 50.0),
    selected="soma@0.50000",
)

voltage = src.line(
    "Selected voltage",
    source=morphology.selection,
    variables={"Voltage": "v"},
    y_unit="mV",
    rolling_window=500.0,
)

src.slider(
    "stimulus",
    label="Stimulus amplitude (nA)",
    get=lambda: stim.amp,
    set=set_stimulus,
    min=0.0,
    max=2.0,
)

cnv.layout(((morphology, voltage), (src.controls_panel,)))
cnv.show(title="NEURON morphology")
~~~

Full showcase:

~~~bash
python examples/neuron/complete_interface.py
~~~

Static surface showcase:

~~~bash
python examples/widgets/surface.py
~~~

## Supported Alpha Surface

- cnv.source(...) for Python callables, iterators, and static data.
- cnv.neuron.source(...) and cnv.jaxley.source(...) for simulator-native sources.
- Source-level line, bar, morphology, and surface views.
- Typed controls and actions used by current examples.
- cnv.layout(...) for single-app panel placement.
- cnv.show(...) with VisPy and PyQt6 desktop rendering.

Views are opt-in. A simulator source can own morphology without displaying a
morphology panel.

## Experimental

These paths are incomplete or not release-supported:

- Notebook frontends and notebook process lifecycle.
- Remote sources and remote actors.
- Source composition and independent multi-source execution.
- Multi-source custom layouts.
- Advanced callback access through backend internals.

Incomplete distributed entrypoints live under cnv.experimental so they are not
mistaken for supported root-level API.

## Documentation

Start with [Getting Started](docs/getting-started.md), then follow the ordered
[Example Path](docs/examples.md).

Build the documentation site locally:

~~~bash
python -m mkdocs build --strict
~~~

## License

Apache License 2.0.
