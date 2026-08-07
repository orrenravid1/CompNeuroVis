# Third-Party Widget Authoring

CompNeuroVis widgets can live in ordinary Python files beside an app. Installing
CompNeuroVis once is enough; a separate package is optional and is useful only
when distributing a reusable plugin.

## The Two Halves

A widget has two deliberately separate halves:

1. Neutral authoring lowers data, geometry, selections, operators, views, and
   visual contributions into canonical CompNeuroVis specs.
2. Each frontend registers how it presents the kinds it supports.

The authoring module must not import Qt or Vispy renderer classes. A backend or
headless process must be able to lower and transport the widget without loading
GUI code.

## Declare A Widget

Implement `Widget` and return an appropriate typed reference:

~~~python
from dataclasses import dataclass

import compneurovis as cnv
from compneurovis.frontends.vispy import register_vispy_plugin
from compneurovis.widgets import PanelRef, Widget


# This records an import string. The renderer module is loaded later by Vispy.
register_vispy_plugin("gauge_vispy:register")


@dataclass(frozen=True, slots=True)
class Gauge(Widget[PanelRef]):
    title: str
    values: object

    def declare(self, context) -> PanelRef:
        data = context.data("value", values=self.values)
        return context.view(
            "gauge",
            self.title,
            inputs={"data": data},
        )
~~~

Use the typed universal path in the app:

~~~python
gauge = src.add(Gauge("Activity", values))
~~~

Optionally expose the same factory as a dynamic source method:

~~~python
cnv.register_widget("gauge", Gauge)
gauge = src.gauge("Activity", values)
~~~

`source.add(...)` remains statically typed. Dynamic names are convenient and
discoverable through `dir(source)`, but static type checkers cannot know them.

## Register The Vispy Half

Put GUI imports in the deferred module named above:

~~~python
from PyQt6 import QtWidgets

from compneurovis.frontends.vispy import register_renderer


class GaugePanel(QtWidgets.QProgressBar):
    def refresh(self, view, inputs, properties, values):
        del view, properties, values
        field = inputs["data"]
        self.setValue(round(100.0 * float(field.values.reshape(-1)[-1])))


def build_gauge(*, panel_id, view_id, title):
    del panel_id, view_id, title
    panel = GaugePanel()
    panel.setRange(0, 100)
    return panel


def register():
    register_renderer("gauge", build_gauge)
~~~

`register_renderer` uses the ordinary `standalone` QWidget lifecycle. Choose a
different registration only when the widget genuinely needs a different owner:

| Need | Registration |
|---|---|
| Ordinary QWidget, plot, table, image, or dashboard | `register_renderer` |
| Layer sharing the standard 3-D camera, canvas, commit, and picking lifecycle | `register_scene_layer` |
| Derived frontend-side data | `register_operator_adapter` |
| Graphical addition owned by another widget | `register_scene_contribution` or `register_plot_contribution` |
| Entirely different panel lifecycle | `register_panel_host` |
| New control or action presentation | `register_control_renderer` or `register_action_renderer` |

Do not create a custom panel host merely to draw a new widget. A host owns
lifecycle and composition policy; a renderer owns presentation.

## Operators And Contributions

`context.operator(...)` may consume ordinary fields or outputs from other
operators. Operator graphs must be acyclic. A Vispy operator adapter resolves its
direct inputs through `OperatorResolveContext.field(...)`; that lookup is
recursive, so downstream adapters do not need to know whether an upstream input is
stored or derived.

An adapter also declares its direct field dependencies, value bindings, and which
property patches affect output. CompNeuroVis expands those declarations
transitively when routing refreshes to views and visual contributions. Keep those
hooks complete: resolution alone is not enough for a live operator.

A visual contribution owns its graphical addition and targets an explicit panel
capability. If it binds a selection, it must declare the geometry that selection
belongs to. The target view is not an implicit owner or source of geometry.

## Controls And Actions

New typed control and action authoring names use `cnv.register_control(...)` and
`cnv.register_action(...)`. Their factories receive `ControlAuthoringContext` or
`ActionAuthoringContext` and lower to neutral specs. Their Vispy presentation is
registered separately.

The final app can attach behavior through the normal `get`, `set(ctx, value)`, or
action callback arguments. A third-party renderer emits through
`ControlRenderContext` or invokes through `ActionRenderContext`; it does not reach
into the built-in controls panel.

Multiple controls panels are normal:

~~~python
simulation = src.controls("Simulation")
display = src.controls("Display")
simulation.slider("dt", label="dt", min=0.01, max=1.0, default=0.1)
display.dropdown("map", label="Color map", options=("bwr", "fire"))
cnv.layout(((plot,), (simulation, display)))
~~~

## Packaging And Discovery

For adjacent app scripts, call
`register_vispy_plugin("module:register")` from the neutral authoring module.

For an installed distribution, expose the same callback through the
`compneurovis.vispy_plugins` Python entry-point group. The installed form does
not get extra privileges; it is only automatic discovery for distributable code.
Built-ins use these same frontend registries.

## Complete Examples

- `examples/extensions/local_gauge/` is an adjacent-script widget requiring no
  separate install. It intentionally demonstrates a complete custom panel host.
- `examples/extensions/cnv_pointcloud_demo/` is an installable conformance
  fixture covering geometry, scoped selection, a Scene3D layer, a plane-slice
  operator and owned overlay, and a separate Scatter2D consumer.

## Boundary Rules

- Canonical identity is `ViewSpec`, `GeometrySpec`, and `OperatorSpec`, not a
  package-owned subclass.
- Frontend-local typed objects use `*RenderConfig` or another clear configuration
  name; they are not canonical authored views.
- A component authors its own graphical contributions. A target renderer exposes a
  narrow capability and does not branch on contributor kinds.
- Selection names the exact authored selection and geometry; entity ids are not
  process-global.
- Built-ins and third parties use the same collision-checked registration calls.
- Notebook rendering remains experimental and is not a second widget-authoring
  contract.
