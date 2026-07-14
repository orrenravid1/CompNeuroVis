# Example Path

Follow examples in this order. Each level assumes ideas introduced above it.

## Beginner

No simulator dependency.

1. examples/custom/sine_wave.py
   Minimal live source, one line, one slider, and actions.
2. examples/widgets/line_plot.py
   Line styles, multiple series, levels, and fixed axes.
3. examples/widgets/controls.py
   Supported typed controls in one panel.
4. examples/widgets/bar_plot.py
   Static categorical values and bar styling.
5. examples/widgets/surface.py
   Small static two-dimensional field rendered as a surface.
6. examples/widgets/morphology.py
   Generic morphology geometry, selection, and selected trace.

Run any example from repository root:

~~~bash
python examples/custom/sine_wave.py
~~~

## Intermediate

These combine multiple capabilities or introduce a simulator source.

1. examples/widgets/grid_slice.py
   Surface, controls, overlay, and linked cross-section.
2. examples/widgets/state_graph.py
   Dynamic node and transition values.
3. examples/custom/fitzhugh_nagumo_backend.py
   Reusable Python model with several plots, controls, and actions.
4. examples/custom/lif_backend.py
   Threshold/reset model with current, voltage, and event views.
5. examples/surface_plot/animated_surface_live.py
   Live field updates and surface controls.
6. examples/surface_plot/surface_cross_section_visualizer.py
   Full linked surface and profile workflow.
7. examples/neuron/hh_point_model_controls.py
   NEURON source with lines and controls, without morphology.
8. examples/neuron/complex_cell_example.py
   NEURON morphology with selection-driven voltage.
9. examples/jaxley/multicell_example.py
   Jaxley morphology, selected voltage, and model controls.

Install matching backend extra before NEURON or Jaxley examples.

## Advanced

These are reference applications rather than first tutorials.

1. examples/neuron/complete_interface.py
   Flagship high-level app: morphology color modes, selection-driven traces,
   controls, reset, and explicit layout.
2. examples/neuron/hh_section_inspector.py
   Morphology plus voltage, gate, and current inspection.
3. examples/neuron/multicell_example.py
   Multi-cell NEURON morphology and linked selection.
4. examples/neuron/signaling_cascade_vis.py
   NEURON-backed signaling mechanisms and multi-series visualization.
5. examples/neuron/c_elegans_visualizer.py
   Imported biological morphology on the same source API.

Some advanced examples require model assets or compiled NEURON mechanisms. Read
their top-of-file instructions before running them.

## Experimental Examples

examples/notebook/ demonstrates notebook process and RFB work. Notebook support
is experimental in 0.4.0.

examples/debug/ contains focused regressions and renderer diagnostics. They are
not part of the learning path or supported showcase.

examples/surface_plot/animated_surface_replay.py demonstrates iterator-style
playback. Treat broader replay/session architecture as experimental.
