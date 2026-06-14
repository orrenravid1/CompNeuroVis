1. Parameter-space regime maps

These are the main visual objects.

Each map should show a 2D parameter sweep where every point is one simulation condition.

For each point, you classify the observed behavior into a categorical regime.

Example panel types:

Panel 1: Plateau duration map

Axes could be:

x-axis: EGL-19 strength
y-axis: EXP-2 strength or leak/repolarization strength

Colors:

no plateau
short finite plateau
long finite plateau
endless plateau / failed recovery

Main message:

Plateau duration is controlled by the balance between plateau-sustaining inward current and repolarizing forces.

Panel 2: Plateau propagation map

Axes could be:

x-axis: gap junction coupling
y-axis: excitability, such as EGL-19 or CCA-1 strength

Colors:

no response
local plateau
partial propagation
full propagation
runaway/global plateau

Main message:

Propagation depends on both local excitability and coupling between compartments.

Panel 3: Functional regime / robustness map

Axes could be another biologically meaningful pair, such as:

EGL-19 strength vs EXP-2 kinetics
EGL-19 strength vs leak
stimulus amplitude vs recovery strength
gap coupling vs recovery strength

Colors:

failed response
functional finite plateau
overlong plateau
endless plateau
ambiguous/unstable

Main message:

The model contains a bounded functional region between failure and pathological persistence.

This panel should probably be the “so what” panel.

2. Representative traces for each regime

For each map, you should show a small set of traces corresponding to the colors on the map.

For example, if Panel 1 has four colors:

no plateau
short plateau
long plateau
endless plateau

then you show one trace for each.

The traces should use the same colors as the regime map.

This lets the audience immediately understand what the map colors mean.

For plateau duration, simple voltage traces are enough.

For propagation, you may want either:

multiple voltage traces from different compartments, or
a space-time heatmap showing voltage across compartments over time.

For poster clarity, propagation probably benefits from a space-time plot more than a normal line plot.

3. Quantitative metrics used to classify regimes

You do not need to show every metric, but you should make clear that the categories are not arbitrary.

Useful metrics:

Plateau duration
onset time
offset time
duration
whether the system returns to baseline
endless plateau yes/no
Propagation
number of compartments recruited
propagation fraction
onset time per compartment
recruitment delay
recruitment order
Functional regime
plateau present yes/no
duration within target range yes/no
propagation fraction
return-to-baseline time
endless plateau yes/no

You can show this as a tiny methods inset:

Regimes were classified from voltage traces using plateau onset/offset, return-to-baseline, and compartment recruitment.

The full classifier details can go in a QR supplement.

4. Sweep metadata

The poster should provide enough information that the sweep feels rigorous.

Not everything needs to be visually prominent, but somewhere you should state:

number of parameter combinations sampled
which parameters were swept
fixed stimulation protocol
compartments recorded
model readout used for classification
whether representative traces are actual examples from the grid

Example:

Each regime map summarizes a 2D parameter sweep. At each grid point, the model was stimulated with a fixed current-clamp protocol and voltage was recorded across pharyngeal compartments. Regimes were classified using plateau duration, return-to-baseline, and propagation fraction.

That gives the audience confidence that the colored maps came from systematic simulation, not handpicked traces.

What the poster should not overemphasize

I would avoid making the poster about detector design, threshold tuning, or CompNeuroVis implementation details. Those are important for your workflow, but they are not the scientific result.

The poster should emphasize:

what was varied
what behavior emerged
how regimes changed across parameter space
what this suggests about pharyngeal plateau control
Clean data package for the poster

For each of the three main panels, you want this bundle:

1. 2D parameter grid
2. categorical regime label for every grid point
3. color legend defining each regime
4. representative trace for each regime
5. short metric note explaining how regimes were classified

That is the core.

Most likely final poster structure
Top

Brief model schematic:

pharyngeal compartments
key currents: CCA-1, EGL-19, EXP-2, leak
coupling between compartments
Middle: three main data panels
Plateau duration
2D regime map
representative voltage traces
Plateau propagation
2D regime map
representative propagation traces or space-time plots
Functional regime organization
2D regime map
representative traces showing failed, functional, overlong, and endless states
Bottom

Short interpretation:

Plateau behavior emerges from competing inward and outward currents.
Propagation depends on excitability and coupling.
Functional behavior occupies a bounded region between failure and runaway plateau states.
Interactive exploration helped identify regime boundaries and representative examples.

That is probably the right level: the poster presents the data products and biological interpretation, while your internal workflow handles how those data were generated.