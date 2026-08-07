# High-Level API

Normal applications should use source-level authoring. AppSpec, RunSpec, fields,
actors, messages, and transports exist for advanced systems but are not required
for ordinary use.

## Create a Source

Generic Python:

~~~python
src = cnv.source(step)
~~~

Static UI or data:

~~~python
src = cnv.source()
~~~

NEURON:

~~~python
src = cnv.neuron.source(
    sections=sections,
    dt=0.025,
    display_dt=0.5,
)
~~~

Jaxley:

~~~python
src = cnv.jaxley.source(
    cells=cells,
    dt=0.025,
    display_dt=0.5,
)
~~~

Generic and simulator-specific sources share view, control, action, and layout
behavior. Simulator source code only specializes stepping, geometry, and
efficient native data collection.

## Add Views

Every view is opt-in and returns a panel handle.

| Method | Purpose |
|---|---|
| src.line(...) | Live or static series |
| src.bar(...) | Categorical values |
| src.surface(...) | Two-dimensional values rendered as a surface |
| src.morphology(...) | Colored and optionally selectable morphology |
| src.grid_slice(...) | Surface cross-section; returns sliced data to plot with a line |
| src.network2d(...) | Node/edge graph with live-colored nodes and transitions |

Generic live readers are plain callables:

~~~python
voltage = src.line(
    "Voltage",
    read=lambda: model.voltage,
    x=lambda: model.time_ms,
    y_unit="mV",
)
~~~

Use `read=` for continuously sampled data. Use `values=` plus an explicit
replacement for snapshots that change only after an application event:

~~~python
spectrogram = src.surface("Spectrogram", values=initial_spectrogram)

def load_recording(ctx):
    model.load_recording()
    ctx.set_data(spectrogram, model.spectrogram)
~~~

Scene-3D widgets own suitable camera defaults. Surface navigation is gentler
than morphology navigation by default. Override one view independently with
`camera_orbit_sensitivity`, `camera_pan_sensitivity`, and
`camera_zoom_sensitivity`.

Simulator-native sources can expose optimized data handles. Selection-driven
traces are one example:

~~~python
morphology = src.morphology(
    variable="v",
    selected="soma@0.50000",
)

voltage = src.line(
    "Selected voltage",
    source=morphology.selection,
)
~~~

Selection is separate from display. Use selectable=False when a morphology is
visual only. Use select_multiple=True only when the application needs multiple
selected entities.

## Add Controls And Actions

Controls are explicit:

| Method | Value |
|---|---|
| src.slider(...) | Bounded scalar |
| src.number(...) | Integer input |
| src.dropdown(...) | One string from fixed options |
| src.checkbox(...) | Boolean |
| src.text(...) | String |
| src.xy_pad(...) | Two bounded scalar values |

Actions:

| Method | Behavior |
|---|---|
| src.button(...) | Visible command |
| src.hotkey(...) | Keyboard command or shortcut to an action |

Backend-bound setters receive context and value:

~~~python
def set_gain(ctx, value):
    model.gain = float(value)


src.slider(
    "gain",
    label="Gain",
    get=lambda: model.gain,
    set=set_gain,
    min=0.0,
    max=2.0,
)
~~~

A control without a setter can remain frontend-owned when it only changes view
presentation.

Use ctx.clear() to clear accumulated display history while preserving prior run
state. Use ctx.reset() for a full model and display reset.

## Arrange Panels

Pass view handles and src.controls_panel to cnv.layout():

~~~python
cnv.layout(
    (
        (morphology, voltage),
        (gates, src.controls_panel),
    )
)
~~~

Each tuple is one row. Items in a row share horizontal space.

Layout belongs to the final app, not to one source. cnv.show() integrates all
declared pieces and launches the frontend:

~~~python
cnv.show(title="My model")
~~~

## Model And Source Responsibilities

Model:

- Owns simulation state and scientific behavior.
- Exposes values and methods.
- Does not know about controls, panels, selection, or rendering.

Source:

- Chooses what model capabilities are exposed.
- Adds readers, optimized collectors, controls, and actions.
- Declares opt-in views.

App:

- Integrates source fragments.
- Owns layout and visible frontend.
- Routes commands back to correct source.

## Experimental Boundaries

Not stable alpha API:

- Notebook process lifecycle.
- Remote sources and actors.
- Source composition.
- Multi-source custom layouts.
- Direct backend access through callback context.
- Custom actor, bus, transport, and frontend assembly.

Incomplete distributed entrypoints live under cnv.experimental rather than the
root API.

## Extend The Widget Vocabulary

Widgets, panel hosts, controls, actions, operators, and graphical contributions
have open authoring and frontend registration contracts. App-local scripts do not
need to be packaged separately. See
[Third-Party Widget Authoring](widget-authoring.md) for the supported workflow and
complete conformance examples.
