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
The built-in Line, Bar, Network2D, Morphology, Surface, GridSlice, and
LevelMarker factories occupy this same registry and are returned by
`cnv.registered_widgets()`; their explicit `source.line(...)`-style methods
provide the statically typed facade.

Authoring names have one owner. Re-registering the exact owning factory is
idempotent, including for built-ins. Widget registrations are deliberately not
replaceable: swapping a factory behind a statically typed built-in method would
make that method's signature dishonest. Controls and actions retain
`override=True` for explicit presentation-authoring replacement, while
cross-category collisions remain errors. A dynamic name must be a public Python
identifier and may not shadow a real source or controls-panel attribute. Control
and action factories must return `ControlRef` and `ActionRef` respectively; an
invalid factory fails at the authoring call with its registered name in the error.

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
| Addition for a custom host capability | `register_visual_contribution_renderer` |
| Entirely different panel lifecycle | `register_panel_host` |
| New control or action presentation | `register_control_renderer` or `register_action_renderer` |

Do not create a custom panel host merely to draw a new widget. A host owns
lifecycle and composition policy; a renderer owns presentation.

Within Vispy, one authored view kind has one ownership model. The same kind cannot
be registered both as a standalone renderer and as a Scene3D layer or refresh
target. Use distinct kind names when two presentations have different lifecycle
owners; otherwise refresh routing would be ambiguous.

## Operators And Contributions

`context.operator(...)` may consume ordinary fields or outputs from other
operators. Operator graphs must be acyclic. A Vispy operator adapter resolves its
direct inputs through `OperatorResolveContext.field(...)`; that lookup is
recursive, so downstream adapters do not need to know whether an upstream input is
stored or derived.

An adapter also declares its direct field dependencies, value bindings, and which
property patches affect output. CompNeuroVis expands those declarations
transitively when routing refreshes to views and visual contributions. Keep those
hooks complete: resolution alone is not enough for a live operator. Every
operator adapter must provide callable `resolve_field(...)`; consuming an
authored operator without a registered adapter raises a direct configuration
error rather than silently behaving like a missing field.

A visual contribution owns its graphical addition and targets an explicit panel
capability. If it binds a selection, it must declare the geometry or exact hit
target that selection belongs to. The target view is not an implicit owner or
source of either.

## Composing Tools Over Existing Widgets

Specialized refs expose independent capabilities rather than hidden widget
internals. A `MorphologyRef`, for example, provides `geometry`, `color`,
`entity_click`, `selected`, and optional `selection` history. A third-party layer
can reuse the exact geometry and current data without guessing ids:

~~~python
context.visual_contribution(
    "my_channel_layer",
    "Sodium density",
    target=morphology,
    capability="scene3d.layers/v1",
    inputs={"density": sodium_density},
    geometries={"morphology": morphology.geometry},
)
~~~

Use `context.snapshot(...)` for explicit N-D data. Its dimension names remain
stable, but a backend callback may atomically resize values and coordinates. This
supports marker, annotation, and other mutable tables without a special collection
type:

~~~python
markers = context.snapshot(
    "markers",
    dims=("marker", "attribute"),
    coords={"marker": (), "attribute": ("x", "y", "z", "r", "g", "b")},
    values=np.empty((0, 6), dtype=np.float32),
)

def place(ctx, entity_id):
    position = ctx.entity_info(entity_id)["position"]
    rows.append((*position, 1.0, 0.2, 0.1))
    ctx.set_data(
        markers,
        rows,
        coords={"marker": marker_ids, "attribute": marker_columns},
    )
    return True  # consume; do not apply the click's linked selection

context.on_entity_click(morphology.entity_click, place)
~~~

Returning false deliberately lets the click fall through to its linked
single/multiple selection policy. Selection presentation remains owned by each
view or contribution; neither a click nor selection implies highlighting.
The click gesture retains the press-origin `HitRecord`; its nearby release
confirms the gesture without repicking mutable renderer state.

Entity ids are one typed convenience, not the definition of selection. A widget
can select a neutral geometric hit—or another data-only result kind—against an
exact hit target:

~~~python
target = context.hit_target("surface")  # rendered from a field, no fake geometry
selected_points = context.selection(
    "surface points",
    hit_target=target,
    item_kind="hit",
    multiple=True,
)
clicked_point = context.click(
    "surface",
    hit_target=target,
    result_kind="hit",
    selection=selected_points,
)

def inspect(ctx, event):
    point = event.value  # HitValue: primitive, world position, normal, depth
    press = event.gesture.press

context.on_click(clicked_point, inspect)
~~~

Declare the same target, selection, and click roles on the consuming view with
`hit_targets=`, `selections=`, and `clicks=`. The frontend creates `HitValue`
directly from `HitRecord`. For another `result_kind`, the registered visual
implements `value_for_hit(hit, result_kind)`; core, source routing, selection
policy, and transports do not change. `entity_click(...)` and
`on_entity_click(...)` use this exact path with `result_kind="entity"`; the
entity-click declaration carries its geometry as result scope, not as hit-target
state. That keeps duplicate entity ids deterministic without coupling generic
pick routes to `GeometrySpec`.

For drag tools, attach a pointer interaction to the same exact neutral hit target.
Click and pointer gestures are sibling canonical consumers. A generic tool uses
`context.pointer(...)` and receives its requested hit-derived value through
`event.value`; it needs no geometry for the neutral `hit` result:

~~~python
drag = context.pointer(
    "surface brush",
    hit_target=target,
    result_kind="hit",
    enabled=paint_mode,
)
context.on_pointer(drag, apply_surface_brush)
~~~

`entity_pointer(...)` is thin authoring convenience that can reuse an entity
click's target and geometry scope. Its `enabled` argument may be a checkbox or
another ordinary boolean binding:

~~~python
paint = context.entity_pointer(
    "paint",
    interaction=morphology.entity_click,
    enabled=paint_mode,
)

def apply_brush(ctx, event):
    if event.phase in ("press", "move") and event.value is not None:
        values[ctx.entity_info(event.value)["index"]] = ctx.get_value(brush_value)
        ctx.set_data(morphology.color, values)

context.on_entity_pointer(paint, apply_brush)
~~~

When enabled, a matching button press captures the gesture only if it begins on
an entity. Presses on empty background continue to pan or rotate the host camera.
The canonical press/move/release/cancel events contain the exact pointer-interaction
id plus a neutral `PointerEvent`: pointer id/type, normalized position and delta,
optional logical coordinates, buttons, canonical modifiers, timestamp, and ordered
geometric `HitRecord` values. `event.value` is the requested current result (or
`None` off the target); entity convenience produces an entity id there. These
facts do not imply clicking, selection, or highlighting. Multiple editor tools
may attach to the same hit route when their mode bindings are mutually exclusive;
simultaneously enabled claimants are an explicit configuration error.

## Controls And Actions

New typed control and action authoring names use `cnv.register_control(...)` and
`cnv.register_action(...)`. Their factories receive `ControlAuthoringContext` or
`ActionAuthoringContext` and lower to neutral specs. Their Vispy presentation is
registered separately.

The final app can attach behavior through the normal `get`, `set(ctx, value)`, or
action callback arguments. A third-party renderer emits through
`ControlRenderContext` or invokes through `ActionRenderContext`; it does not reach
into the built-in controls panel.

A custom panel host receives `ResolvedControl` and `ResolvedAction` items
from `PanelHostContext.controls_and_actions(panel_id)`. Their `ref` fields
carry fragment scope, and a resolved control also carries its scoped
`value_ref`. The nested `spec` remains the unchanged neutral
`ControlSpec` or `ActionSpec`. Pass that local spec to a registered
renderer; use the resolved refs for routing and host bookkeeping.
Forward the whole item to `PanelHostContext.control_changed(item, value)` or
`PanelHostContext.action_invoked(item, payload)` when the host emits an
interaction.

Multiple controls panels are normal:

~~~python
simulation = src.controls("Simulation")
display = src.controls("Display")
simulation.slider("dt", label="dt", min=0.01, max=1.0, default=0.1)
display.dropdown("map", label="Color map", options=("bwr", "fire"))
cnv.layout(((plot,), (simulation, display)))
~~~

Hotkeys are portable bindings on ordinary semantic actions:

~~~python
reset = simulation.hotkey("R", fn=lambda ctx: ctx.reset())
simulation.button("reset", label="Reset", hotkey=reset)
simulation.hotkey("Ctrl+R", fn=lambda ctx: ctx.show_status("Ctrl+R"))
~~~

`R` and `Ctrl+R` are distinct. Basic Control, Alt/Option, Shift, and
Meta/Command combinations are normalized across frontend adapters. A fresh press
invokes every matching fragment-scoped action once; holding the key does not
repeatedly invoke it. Native editable controls receive keyboard input first, and
an unmatched key remains available to the frontend's normal behavior. Hotkeys do
not use a raw application-wide backend key callback.

## Packaging And Discovery

For adjacent app scripts, call
`register_vispy_plugin("module:register")` from the neutral authoring module.

For an installed distribution, expose the same callback through the
`compneurovis.vispy_plugins` Python entry-point group. The installed form does
not get extra privileges; it is only automatic discovery for distributable code.
Built-ins use these same frontend registries.

The generic custom-capability API is also public from
`compneurovis.frontends.vispy`:
`VisualContributionHostContext`, `create_visual_contribution_renderer`, and
`register_visual_contribution_renderer`. Scene3D and Plot2D are convenience
capabilities built over that same registry, not the only possible targets.

## Complete Examples

- `examples/extensions/local_gauge/` is an adjacent-script widget requiring no
  separate install. It intentionally demonstrates a complete custom panel host.
- `examples/extensions/cnv_pointcloud_demo/` is an installable conformance
  fixture covering geometry, scoped selection, a Scene3D layer, a plane-slice
  operator and owned overlay, and a separate Scatter2D consumer.
- `examples/extensions/morphology_tools_demo/` is an adjacent-script composition
  with simultaneous morphology channels, click-routed paint/marker tools, a
  resizable marker snapshot, ordinary selection, and no package changes.

## Boundary Rules

- Canonical identity is `ViewSpec`, `GeometrySpec`, and `OperatorSpec`, not a
  package-owned subclass.
- Selectable geometries declare `entity_ids` and scalar per-entity arrays in
  `GeometrySpec.data`. Use the generic `metadata["entity_fields"]` mapping
  when interaction code needs stable names for scalar or structured per-entity
  values, and reserve
  `metadata["entities"]` for genuinely irregular per-entity records.
- Frontend-local typed objects use `*RenderConfig` or another clear configuration
  name; they are not canonical authored views.
- A component authors its own graphical contributions. A target renderer exposes a
  narrow capability and does not branch on contributor kinds.
- Selection names the exact authored selection and geometry; entity ids are not
  process-global.
- Built-ins and third parties use the same collision-checked registration calls.
- Python-only selector conveniences such as `slice(...)` lower to data-only
  canonical selector mappings before entering `ViewSpec`.
- `cnv.show()` consumes one ambient authoring session, while a direct
  `source.show()` detaches that source; a later app cannot accidentally relaunch
  it.
- Notebook rendering remains experimental and is not a second widget-authoring
  contract.
