# CompNeuroVis

CompNeuroVis turns computational neuroscience simulations and data into
interactive desktop applications. A source exposes model values and commands.
You opt into plots, morphology, controls, and layout. CompNeuroVis integrates
them when you call cnv.show().

## Start Here

1. Follow [Getting Started](getting-started.md) to install CompNeuroVis and run
   a live line plot.
2. Read [High-Level API](high-level-api.md) for the source, view, control, and
   layout model.
3. Work through [Example Path](examples.md) from beginner to advanced.

## Small Mental Model

~~~python
import compneurovis as cnv

src = cnv.source(step)
plot = src.line("Voltage", read=read_voltage)
src.slider("gain", label="Gain", min=0.0, max=2.0, set=set_gain)

cnv.layout(((plot,), (src.controls_panel,)))
cnv.show()
~~~

- Model: your simulation or data.
- Source: adapter exposing values and commands.
- Views: panels you explicitly request.
- Layout: arrangement of panel handles.
- Show: integration and launch.

Simulator-specific sources use the same shape:

~~~python
src = cnv.neuron.source(sections=sections)
src = cnv.jaxley.source(cells=cells)
~~~

Owning morphology does not automatically display it. Add a morphology view only
when the application needs one.

## Alpha Scope

Version 0.4.0 is an alpha release. APIs may change before 1.0.0.

Supported release path:

- Inline Python sources.
- NEURON and Jaxley sources.
- Line, bar, morphology, and surface views.
- Typed controls and actions.
- Explicit layouts and the VisPy desktop frontend.

Notebook, remote, source-composition, and advanced multi-actor workflows remain
experimental.
