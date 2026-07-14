# Getting Started

## Requirements

- Python 3.11.
- A desktop session capable of opening PyQt6 windows.
- Optional NEURON or Jaxley installation for simulator examples.

## Install

Alpha release:

~~~bash
pip install --pre compneurovis
~~~

Current checkout:

~~~bash
pip install -e .
~~~

Optional simulator integrations:

~~~bash
pip install -e ".[neuron]"
pip install -e ".[jaxley]"
~~~

## First Live App

Create a Python file with:

~~~python
import math

import compneurovis as cnv


state = {
    "time_ms": 0.0,
    "frequency_hz": 1.0,
}


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

Run it as a normal Python script. You should see a live trace and frequency
slider.

Repository version:

~~~bash
python examples/custom/sine_wave.py
~~~

## What Each Line Does

- cnv.source(step) creates a source and calls step as the app runs.
- src.line(...) samples the supplied readers into a line panel.
- src.slider(...) adds one explicit control and connects it to a setter.
- src.controls_panel is the panel handle containing controls and actions.
- cnv.layout(...) places returned panel handles.
- cnv.show(...) launches the integrated application.

The model remains ordinary Python. It does not import UI concepts or know which
views are present.

## Next Steps

- Learn every supported high-level construct in
  [High-Level API](high-level-api.md).
- Follow [Example Path](examples.md) instead of choosing examples at random.
- Install the NEURON extra before starting simulator-backed examples.
