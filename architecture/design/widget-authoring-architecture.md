---
title: Widget Authoring Architecture and Refactor Record
summary: Current widget authoring architecture, third-party registration contracts, implemented package ownership, standing coding principles, and known limitations.
status: active architecture record
date: 2026-08-09
---

# Widget Authoring Architecture and Refactor Record

This is the source of truth for CompNeuroVis widget authoring and extension
architecture as implemented today. It replaces the completed widget-taxonomy,
third-party-conformance, panel/control/layer, and building-a-widget proposals. It
also retains the still-relevant direction from the older Authoring Layer proposal.

The implementation in `src/` remains authoritative. This record explains why its
boundaries exist, what the completed refactor proved, how an author uses the
current contracts, and which adjacent work remains open.

## 1. Current outcome

For the 0.4 alpha, the target is deliberately bounded: an author can define a
widget, control, action, contribution, or panel host in ordinary app-adjacent
Python; lower it to transport-safe canonical specs; register its Vispy half
predictably; compose independent source fragments; and receive an immediate,
specific error for an invalid registration. Packaging is optional. Notebook
promotion, remote role policy, the adaptive presentation scheduler, and exhaustive
hardening of unsupported low-level paths remain follow-on work rather than alpha
release blockers.

The behavioral de-privileging work is complete:

- Every built-in view lowers to `ViewSpec(kind=...)`; core contains no
  widget-specific view classes.
- Geometry, operators, and independently authored visual additions cross the
  canonical boundary as core-owned, kind-keyed, data-only envelopes.
- Built-in and third-party renderers use the same collision-safe registration
  contracts.
- App-local widget scripts and installed entry-point plugins use one deferred
  Vispy discovery callback; app-local authoring does not require packaging.
- `source.add(Widget(...))` is typed. `register_widget(...)` optionally exposes a
  dynamic `source.<name>(...)` convenience without editing CompNeuroVis.
- Built-in widget factories occupy that same public registry and typed source
  methods are their static facade; `registered_widgets()` therefore reports
  first- and third-party widgets together.
- Panel hosts are registered frontend-local lifecycles. Scene3D and Controls are
  ordinary registered hosts rather than core-blessed panel categories.
- Controls are explicitly owned by independently placeable control panels. Control
  authoring and frontend presentation kinds have open registries, and built-ins use
  them.
- Actions have the same two-sided registration shape: `register_action(...)` adds
  source/control-panel authoring sugar, while each frontend registers presentation
  independently. Button and Hotkey use that public authoring registry.
- Scene and plot additions use `VisualContributionSpec`; the component that authors
  a slice or marker owns its graphical contribution. Its target renderer does not
  branch on the contributor kind.
- Visual contributions are addressed to their owning panel, not borrowed through
  that panel's first view. Viewless and future multi-view hosts therefore remain
  expressible.
- Click interactions and selections are distinct, scoped, fragment-safe concepts.
  A geometry-scoped `EntityClickSpec` may optionally link to a `SelectionSpec` for
  default selection behavior. A view independently chooses whether and how it
  consumes selection state; selection itself never implies highlighting.
- GridSlice and point-cloud PlaneSlice are sibling spatial-slicing implementations.
  Their outputs are ordinary data consumed by Line or Scatter without consumer
  knowledge of the originating operator.
- Surface grid coordinates have one owner, the field. The redundant
  `GridGeometrySpec` path is gone.
- Surface, Morphology, Line, Bar, Network2D, and GridSlice author through the same
  public context primitives available to third parties.
- Vispy discovery always installs the first-party manifest before app-local or
  installed callbacks. Scene-layer registration preflights its render config,
  refresh schema, target ownership, and immutable schema snapshot before making
  any registry visible.
- Dynamic authoring registrations must be reachable public Python identifiers and
  cannot shadow real source or `ControlsRef` attributes. Control and action
  factories are checked for their promised ref type at the call site.
- Python slice selectors lower to a neutral data mapping before entering
  `ViewSpec`, so authoring convenience does not leak a Python-only object across
  the canonical boundary.
- Each Vispy view kind has one unambiguous lifecycle owner: it is either a
  standalone renderer or a Scene3D layer/refresh target, never both.
- Showing an ambient app consumes that declaration session. Direct
  `source.show()` detaches the launched source as well, so later authoring cannot
  accidentally compose a previously launched source.
- The experimental notebook frontend consumes the same registered Vispy panel
  lifecycle graph and neutral control/action specs through one generic render
  actor. It has no widget-kind actors, no environment-selected topology, and no
  second widget-authoring contract.

The app-local `examples/extensions/cnv_pointcloud_demo` fixture proves the difficult
path end to end without another package install: PointCloud3D, a plane-slice
operator and owned 3-D overlay, projected Scatter2D output, controls, scoped
picking, duplicate local ids across fragments, spawned-process transport, deferred
frontend discovery, and real GUI rendering. `examples/extensions/local_gauge`
proves that an adjacent script can also add a custom panel host without a framework
edit. Installed entry-point discovery is tested independently from either example.

The structural organization pass is now complete for the supported desktop/source
path. First-party components, registries, controls, panel lifecycles, desktop
coordinators, inline session/source responsibilities, core runtime machinery, and
simulator source/runtime/IO owners now have explicit package homes. The experimental
notebook frontend now owns its RunSpec placement, generic raster projection, and
notebook-native presentation registries in its own package.

Recent follow-through also established that:

- Line and Bar are sibling ordinary standalone renderers over a shared Plot2D host;
  neither is a panel kind or a subclass of the other.
- Plot2D hosts receive an explicit canvas factory. The residual `canvas_type`
  convention has been removed.
- A binding-backed selector may update the title inside a line canvas while the
  surrounding panel title remains independent and changeable through its own
  authored path.
- Simulator-specific selection recording is data authoring: for example,
  `NeuronSource.record_selection(...)` returns a `DataRef`, and the generic Line
  component consumes it without simulator knowledge.
- Consumer-authored retention requirements are discovered generically, including
  operator and visual-contribution inputs; producer retention is not inferred from
  a privileged Line type.
- Refresh routing is registry-driven, but refresh admission is still fixed-rate and
  locally decided by panel lifecycles. The app-wide target is recorded in the
  [Adaptive Presentation Scheduler proposal](proposals/adaptive-presentation-scheduler.md).
- LevelMarker is now an independently attached widget contribution rather than a
  Line/Bar constructor option. The marker owns both declaration and rendering;
  `source.level_marker(plot, value)` merely names its target capability.
- Control-panel authoring may select any registered `panel_kind`. Panel-host
  lifecycles receive controls and actions through neutral context services rather
  than inheriting from the built-in controls host.
- Control and action renderers receive small host-independent contexts. They emit
  values or invoke actions through the canonical interaction route and never
  receive the concrete `ControlsPanel`.
- Control refresh targets carry the owning panel id; changing one value or control
  declaration does not wake unrelated controls hosts.
- `PanelPatch` remounts exactly the affected registered host from the live
  projection. The residual `PanelSpec.host_kind` distinction is gone; `kind` is
  the single host-selection contract.
- Entity inspection is geometry-kind-neutral. Any geometry can declare
  `entity_ids`, scalar per-entity arrays, and explicit `metadata["entities"]`
  without a frontend morphology branch.
- The simulator sources compose the ordinary Morphology widget over a neutral
  `GeometryRef` and backend-produced color `DataRef`; they no longer call a
  simulator-privileged morphology declaration helper.
- Repeated simulator morphology widgets do not share hidden selection state.
  NEURON allocates ordinary per-widget display/history bindings; Jaxley may share
  its native voltage fields while routing every exact `SelectionSpec`
  independently.
- Unbound `ValueChange` keys remain values; simulator backends do not turn them
  into arbitrary object attributes. Model mutation occurs only through an
  explicitly registered typed control binding.
- The old overloaded inline `session.py` is split: `inline/app.py` owns
  `InlineApp`, while `inline/authoring.py` owns the ambient module-level facade.

## 2. Architectural model

### 2.1 Widget component versus distribution

A widget is a cohesive component, not necessarily a separately installed Python
distribution. Built-ins remain in the single CompNeuroVis wheel. A user widget may
be one adjacent script; packaging is optional for distribution and reuse.

A first-party component owns its typed authoring declarations, validation helpers,
and frontend implementations. Those may live in sibling modules within one internal
component package, but import direction remains strict: importing authoring must not
import Vispy, Qt, or another frontend.

### 2.2 Canonical boundary

Package-owned Python classes never define canonical identity. `AppSpec` and
`RunSpec` carry only core-owned specs, immutable values, kind strings, and scoped
references. A frontend reconstructs any local typed render configuration after it
recognizes the registered kind.

The canonical names are deliberately unqualified: `ViewSpec`, `GeometrySpec`, and
`OperatorSpec`. They are the representation used by every built-in and third-party
component, so calling them `Extension*Spec` would falsely describe third-party
authoring as a separate path. Frontend-local typed values use configuration names
instead: Vispy renderers may reconstruct `LinePlotRenderConfig`,
`SurfaceRenderConfig`, or another `ViewRenderConfig` subtype. A render config is
not an authored core view and does not inherit `ViewSpec`.

Likewise, the ordinary one-view QWidget lifecycle is the `standalone` panel host.
The word *extension* is reserved for genuine library extension points, plugin
discovery, and third-party example/distribution organization; it is not a
canonical spec category, renderer path, or host kind.

This boundary is required by the
[App Configuration Matrix](app_configuration_matrix.md). It keeps Unity, Web,
remote transport, replay, headless, observer, broadcast, and aggregation rows
expressible without importing a Python widget implementation.

### 2.3 Ownership rules

- Core owns the language-neutral protocol and canonical data model.
- Inline owns generic source authoring, lowering, bindings, and data producers.
- Simulator backends own simulator construction, stepping, collection, geometry
  conversion, and optimized native paths.
- A component owns its widget-specific authoring and renderer implementations.
- A frontend owns discovery and registrations for capabilities it supports.
- An operator owns its computation and independently authored visual contribution.
- A target host exposes a narrow capability; it does not know contributor kinds.
- A source produces data. A widget consumes or presents it. Consumer-specific
  presentation policy must not leak backward into a backend.

### 2.4 Authoring path

A widget implements `Widget[Ref]` and declares through
`WidgetAuthoringContext`. The public primitives are:

- `data(...)`, `series(...)`, and `grid(...)` for fields;
- `geometry(...)` for genuine geometry not already represented by a field;
- `selection(...)` for scoped entity selection;
- `entity_click(...)` for a geometry-scoped click, optionally linked to selection;
- `operator(...)` for computed data;
- `view(...)` for a kind-keyed view and its panel;
- `visual_contribution(...)` for an independently authored graphical layer.

The declaration returns its own typed ref. Authors may use
`source.add(MyWidget(...))` directly or register a dynamic source name.

Controls and actions have parallel authoring registries. A
`register_control(...)` factory receives `ControlAuthoringContext`; a
`register_action(...)` factory receives `ActionAuthoringContext`. Registered names
appear on both `source.<name>(...)` and a specific `ControlsRef`, so a third party
can add a new control or action presentation without editing the source facade.
Built-in control and action factories live in separate composition modules and
register through the same contracts.

A Vispy plugin callback registers whichever independent capabilities it provides:

- `register_renderer(...)` for an ordinary standalone QWidget;
- `register_panel_host(...)` for a new host lifecycle;
- `register_scene_layer(...)` for content mounted in Scene3D;
- `register_operator_adapter(...)` for frontend-side operator resolution;
- visual-contribution renderers for Scene3D or Plot2D additions.

The callback is frontend-only. Canonical lowering and backend execution must work
without importing it.

### 2.5 Present-day authoring workflow

Normal application authoring remains source-level and package-local:

```python
import compneurovis as cnv

src = cnv.source(step)
gain = src.slider(
    "gain",
    label="Gain",
    min=0.0,
    max=2.0,
    default=1.0,
)
trace = src.line("Signal", read=read_signal, x=read_time)
cnv.layout(((trace,), (src.controls_panel,)))
cnv.show()
```

NEURON and Jaxley sources inherit the same widget and control facade. Their source
packages add only simulator-specific data collection, geometry, stepping, and
optimized recording conveniences.

A reusable widget implements the small public `Widget[Ref]` contract:

```python
from dataclasses import dataclass

import compneurovis as cnv
from compneurovis.widgets import PanelRef, Widget


@dataclass(frozen=True, slots=True)
class Gauge(Widget[PanelRef]):
    name: str
    values: object

    def declare(self, context) -> PanelRef:
        data = context.data("value", values=self.values)
        return context.view(
            "gauge",
            self.name,
            inputs={"data": data},
        )


gauge = src.add(Gauge("Activity", values))
```

`source.add(...)` is the typed universal path. App-local or installed code may also
call `cnv.register_widget("gauge", Gauge)` to expose the same factory dynamically as
`source.gauge(...)`. Dynamic methods appear in `dir(source)` and use the same
`add()` funnel, but cannot be visible to static type checkers. A separately
installed distribution is not required: `examples/extensions/local_gauge` and
`examples/extensions/cnv_pointcloud_demo` prove the adjacent-script form at two
levels of complexity, while installed entry-point discovery uses the same callback
contract and is tested independently.

### 2.6 Authoring context and canonical products

`WidgetAuthoringContext` allocates a private namespace for every attached widget,
so repeated instances receive distinct ids. Its public primitives and canonical
products are:

| Primitive | Meaning | Canonical product / authoring ref |
|---|---|---|
| `data(...)` | Static or callable-backed one-dimensional snapshot | `FieldSpec`, `DataRef` |
| `series(...)` | Append-semantics time series | `FieldSpec` plus `FieldAppend`, `DataRef` |
| `grid(...)` | Static or callable-backed coordinated 2-D field | `FieldSpec`, `DataRef` |
| `require_retention(...)` | Consumer requirement on an append dimension | `FieldRetentionSpec` |
| `geometry(...)` | Immutable geometry that is not already a field | `GeometrySpec`, `GeometryRef` |
| `selection(...)` | Scoped selection over one geometry | `SelectionSpec`, `SelectionRef` |
| `entity_click(...)` | Geometry click with an optional default selection link | `EntityClickSpec`, `EntityClickRef` |
| `operator(...)` | Kind-keyed computed data | `OperatorSpec`, output `DataRef` |
| `view(...)` | Kind-keyed view plus its owning panel | `ViewSpec`, `PanelSpec`, `PanelRef` |
| `visual_contribution(...)` | Owner-authored graphics in another panel capability | `VisualContributionSpec` |

Bindings nested in view, operator, and contribution properties lower to canonical
`ValueBindingSpec` values. Fields, geometries, selections, entity clicks, operators, views,
contributions, panels, and values are fragment-scoped during app integration.
Frontend renderers receive the resolved fragment-local resources rather than
reaching into a source or simulator.

`DataRef` intentionally describes only data identity plus useful authoring metadata
such as series dimension, selectors, and unit. It does not name a consumer.
`PanelRef` is layout identity. Specialized refs may expose several independent
capabilities: `MorphologyRef`, for example, exposes its panel, scoped selection,
authored click interaction, and optional optimized selection-history data.

### 2.7 Data, operator, and graphical ownership

The owner that introduces a behavior owns its neutral declaration and its frontend
implementation:

- A data producer owns sampling and emission.
- A consumer may declare retention needs but does not dictate producer mechanics.
- An operator owns computed output data. A consumer receives an ordinary `DataRef`
  and does not branch on the operator kind.
- A visual addition is authored as a contribution targeted at an explicit panel
  and host capability. The target widget makes no room for contributor kinds and
  does not import them. Refresh identity is `(panel_id, contribution_id)`, so a
  contribution does not assume that its host has exactly one view.

Operator inputs may name fields or other operators. Canonical validation rejects
cycles. A frontend adapter's resolve context follows upstream operator outputs
recursively, while its dependency and value-binding hooks describe direct output
dependencies; the refresh planner expands them transitively for every consuming
view and contribution. A contribution that binds a selection must also declare
that selection's geometry, so it cannot silently borrow geometry ownership from a
target view.

GridSlice demonstrates the complete composition. It consumes a Surface field,
declares a `grid_slice` operator, contributes its own overlay into the Surface's
`scene3d.layers/v1` capability, and returns sliced profile data. A separate Line
consumes that data. The point-cloud fixture repeats the pattern with PlaneSlice and
Scatter2D: PlaneSlice owns the finite slab overlay and projected data; PointCloud3D
and Scatter2D remain unaware of it.

GridSlice remains the implemented regular-grid operator today. PlaneSlice proves
the more general spatial ownership model and may eventually subsume the regular
grid specialization, but they are not currently aliases and no compatibility path
pretends otherwise.

LevelMarker follows the same rule in Plot2D. It is a contribution owned by the
marker component, not a special conditional inside Line or Bar. It is authored
after its target exists:

~~~python
trace = src.line("Voltage", read=read_voltage)
threshold = src.slider(
    "threshold", label="Threshold", min=-80.0, max=20.0, default=-20.0
)
src.level_marker(trace, threshold, color="red")
~~~

### 2.8 Vispy discovery and registration contracts

A neutral widget declaration must lower without importing Qt or Vispy. Its Vispy
implementation is discovered later through one callback:

- app-local code records `register_vispy_plugin("module:register")`; this stores an
  import string and defers the import until frontend construction;
- installed distributions expose the same callable through the
  `compneurovis.vispy_plugins` entry-point group;
- `register_first_party_vispy()` is the explicit built-in composition root and
  calls the same registries as third-party callbacks.

Importing a first-party Vispy implementation does not mutate a registry. The
composition root explicitly invokes every first-party component callback, making
the complete built-in capability manifest visible in one place.

The current Vispy registration seams are:

| Registration | Responsibility |
|---|---|
| `register_renderer(kind, factory)` | Ordinary standalone QWidget host with `refresh(view, inputs, properties, values)` |
| `register_scene_layer(...)` | Typed Scene3D layer reconstruction, refresh schema, rendering, commit participation, and picking |
| `register_operator_adapter(kind, adapter)` | Operator dependency, binding, patch-impact, and output-field resolution |
| `register_scene_contribution(...)` | Contribution renderer for `scene3d.layers/v1` |
| `register_plot_contribution(...)` | Contribution renderer for `plot2d.layers/v1` |
| `register_visual_contribution_renderer(capability, ...)` | Contribution renderer for a third-party host capability |
| `register_panel_host(kind, lifecycle)` | Complete construction, refresh ownership, visibility, sizing, and disposal for a panel kind |
| `register_control_renderer(...)` | QWidget presentation for a control presentation kind |
| `register_action_renderer(...)` | QWidget presentation for an action kind |
| `register_frame_policy(kind, ...)` | Experimental notebook raster service level for a neutral view kind |

All registries reject collisions unless their public contract explicitly permits an
intentional override. Missing renderer, host, contribution, or control support
raises a precise error including the live registered set.

Dynamic authoring names share the callable facade presented by Source and
`ControlsRef`. Registration therefore accepts only public Python identifiers and
rejects names already owned by either facade. A factory registered as a control or
action must return the corresponding ref type immediately; arbitrary return values
do not survive until layout or frontend construction.

The standalone-renderer and Scene3D registries also coordinate ownership. Because
refresh schemas are keyed by authored view kind, accepting the same kind in both
registries would make dispatch order-dependent. The alpha contract rejects that
configuration and asks the author to give distinct lifecycle presentations
distinct kind names.

### 2.9 Panels, Plot2D, Scene3D, and controls

`panel_kind` selects a registered frontend host lifecycle; it is not a closed core
enum. Vispy currently registers:

- `standalone`: the normal one-view QWidget host used by Line, Bar, Network2D,
  Scatter2D, gauges, and most standalone widgets;
- `scene_3d`: a shared camera/canvas/picking host for registered 3-D layers and
  owner-authored contributions;
- `controls`: an independently placeable typed-controls host;
- any third-party kind registered through `register_panel_host(...)`.

`PanelSpec.kind` is the only host discriminator; there is no secondary
`host_kind` escape hatch. A `PanelPatch` is applied to the actor-local projection
and remounts only that panel through its registered factory, so custom panel kinds
participate in title, content, and resulting visibility changes without a controls-only
branch. `PanelHostContext.app_spec` resolves the live projection rather than the
startup blueprint.

A host lifecycle implements the public construction/refresh/visibility/disposal
protocol. It may additionally expose an `inspection_surfaces` mapping for
frontend tooling such as viewport or controls inspection, but that mapping is not
required to be a valid host and does not define its behavior.

There is intentionally no privileged Plot2D panel kind. Line and Bar are ordinary
standalone renderers that use a shared `Plot2DHostPanel` implementation detail and
pass their concrete canvas factory explicitly. Plot2D exposes a narrow contribution
surface, so markers can add graphics without Line or Bar knowing their kinds.

Scene3D exists because camera, picking, canvas commit, and several independently
owned layers need one shared transaction. It is still an ordinary registered host,
not a core-blessed 3-D view type. A third party registers a Scene3D layer through
the same API as Surface and Morphology, or registers a different complete panel host
when the Scene3D capability is not appropriate.

Controls are widgets with explicit owners. `source.controls("Playback")` creates a
second placeable `ControlsRef`; `panel.slider(...)`, `panel.dropdown(...)`, and the
other typed calls add controls to that panel. The familiar `source.slider(...)`
methods delegate to the default `source.controls_panel`.

The controls widget is not tied to the built-in host. A third party can register a
different host and select it while retaining the ordinary typed control API:

~~~python
rack = src.controls("Instrument rack", panel_kind="knob_rack")
gain = rack.slider(
    "gain", label="Gain", min=0.0, max=2.0, default=1.0, set=set_gain
)
cnv.layout(((trace,), (rack,)))
~~~

That host obtains the panel's controls and actions from `PanelHostContext`. It
does not subclass or reach into the first-party `ControlsPanel`.

The host boundary does not rewrite canonical specs to add application scope.
`controls_and_actions(panel_id)` returns frontend-local `ResolvedControl` and
`ResolvedAction` items. Both expose the scoped `ref` plus the unchanged
fragment-local `spec`; controls additionally expose the scoped `value_ref`.
This keeps duplicate local names in independent fragments collision-free while
preserving the core invariant that `ControlSpec.id`, `ControlSpec.value_key`,
and `ActionSpec.id` are local strings.
Panel hosts return interactions through `control_changed(resolved, value)` and
`action_invoked(resolved, payload)` so scope is never reconstructed from a
local spec.

Control authoring kinds and Vispy control presentation kinds are independently
registered. Built-ins currently register Slider, Number, Dropdown, Checkbox, Text,
and XYPad through these public seams. `button(...)` and `hotkey(...)` author actions,
not arbitrary controls. The explicit typed methods remain the supported public
surface; there is no generic user-facing control escape hatch.

Action authoring is equally open. `register_action(name, factory)` exposes a
factory through both a source and a chosen `ControlsRef`; the factory lowers
through `ActionAuthoringContext.action(...)` to neutral `ActionSpec`. Button and
Hotkey are first-party registrations in that registry, not names interpreted by
the frontend or runtime. In particular, an action named `reset` has no magic
meaning; reset behavior exists only when an authored callback explicitly calls
`ctx.reset()`.

An action may opt into `entity_click_mode` as a temporary tool. The frontend then
passes both the clicked entity id and the authored `EntityClickSpec` id in the
action payload. The name deliberately does not mention selection: the action may
inspect, edit, place, or explicitly update selection according to its own policy.

A third-party control preserves the same declaration/presentation split. Its
`register_control(...)` factory calls `ControlAuthoringContext.control(...)` and
passes through the standard `get`, `set`, and `send_to_backend` arguments.
The final application therefore attaches behavior with `set(ctx, value)` or
binds the returned `ControlRef` into widget properties without knowing which
frontend renders the control.

The Vispy half receives `(ControlRenderContext, ControlSpec, current_value)` and
returns a `QWidget`. A renderer calls `context.emit(value)` when the user edits
the widget. It never receives `ControlsPanel` or calls a host callback directly.
That emission enters the ordinary frontend value route: update the projected
value, refresh dependent views, and send `ValueChange` to the backend when the
neutral control requested it. First-party control renderers use this exact context;
their construction code does not live behind private host helpers.

~~~python
def render_knob(context, control, current):
    knob = KnobWidget(value=current)
    knob.valueChanged.connect(context.emit)
    return knob


register_control_renderer("knob", render_knob)
~~~

Action renderers have the parallel
`(ActionRenderContext, ActionSpec, current_values)` contract and call
`context.invoke()`. The built-in button uses that route; action kinds do not gain
privilege by living in the standard controls host.

### 2.10 Geometry entity metadata and interaction

Picking and inspection do not reconstruct a built-in geometry class. A
`GeometrySpec` opts into generic entity lookup by putting stable
`entity_ids` in `data`. Scalar arrays of the same length are exposed as
per-entity fields, and richer records may be declared under
`metadata["entities"][entity_id]`. A compact
`metadata["entity_fields"]` mapping may give those arrays interaction-facing
names without duplicating a record for every entity; its keys are exposed names
and its values are keys in `data`. Frontend interaction contexts resolve that
neutral structure for every registered geometry kind.

An interactive scene layer returns `EntityPick(interaction_role, entity_id)`.
The frontend resolves that role through the authored view's `entity_clicks`
mapping and routes the exact `EntityClickSpec` id to the authoritative backend.
The click spec owns its geometry and may optionally name a selection. A backend
tool gets first refusal; only an unconsumed click with an explicit selection link
applies the shared single/multiple selection policy and emits `ValueChange`.

The view's separate `selections` mapping means only that the renderer consumes
that state. The renderer may highlight it, filter data, label entities, drive an
overlay, or give it no visual treatment. A view may therefore expose clicks with
no selection, consume selection without being clickable, or opt into both.
`entity_info(...)` follows an explicit selection's geometry or the active click
interaction's geometry; it never scans for the first matching entity id. Multiple
click roles and duplicate ids across geometries remain deterministic.

This is the editor seam. A NeuroML-style backend may consume authored clicks for
paint, connect, delete, placement, or inspection tools without mutating selection.
It may also explicitly change any authored selection when a tool intends that
coupling. Observer and partial-authority runtimes can reject either operation at
the command-policy boundary without changing widget or renderer code.

Selection is state, not a broad data-refresh command. A producer that is genuinely
selection-dependent declares the exact selection id it consumes. A selection
change may therefore reshape that producer's own field, but it cannot replace,
clear, recenter, or otherwise wake independent fields and recorders.

`MorphologyGeometry` exposes its section, location, and label arrays through
that same neutral `entity_fields` mechanism. It remains a concrete geometry
convenience, not a widget and not a privileged frontend protocol.

### 2.11 Current refresh behavior and open scheduling work

`AppUpdateProcessor` applies messages to the projection, coalesces compatible field
appends, and asks `RefreshPlanner` for affected neutral targets. `PanelManager`
queues those targets on the mounted lifecycle that accepts them and asks pending
lifecycles to flush within the frontend turn's soft deadline.

Current cadence is lifecycle-local:

- a standalone view inherits a 15 Hz cap when `max_refresh_hz` is `None`;
- Line currently authors `0.0`, which opts out of that additional cap;
- Scene3D defaults to 8 Hz when a view has no explicit cap;
- controls refresh when their lifecycle is marked dirty;
- pending targets coalesce as sets, and the projection always advances first.

Within the frontend turn budget, pending panel lifecycles are visited in
least-recently-served order. This is a kind-neutral starvation guard for built-in
and third-party hosts, not the proposed adaptive scheduler: it neither predicts
cost nor changes sampling, transport, retention, or projection semantics.

The neutral whole-view fallback target is `RefreshTarget("view", view_id)`;
`"standalone"` is a host implementation name, not refresh vocabulary. Visual
contribution targets instead carry `panel_id` and `contribution_id`, allowing a
registered capable host with no primary view to own and refresh additions.

These rates describe today's implementation, not the final doctrine. The scheduler
does not yet compare the benefit, measured cost, staleness, visibility, interaction
state, or outstanding paint work of all dirty panels. The
[Adaptive Presentation Scheduler proposal](proposals/adaptive-presentation-scheduler.md)
defines the target without moving presentation policy into producers or adding
widget-kind branches.

Line's binding-backed selectors are resolved during refresh. A selected segment may
therefore update the title inside the plot canvas. That does not implicitly mutate
the surrounding `QGroupBox`/panel title; the two presentation properties remain
independent.

### 2.12 Intentional asymmetries

- Built-ins may have explicit typed `source.line(...)`-style methods in
  `SourceWidgetAPI`. Third-party dynamic names cannot be statically typed; their
  fully typed path is `source.add(...)`.
- Refs are widget-specific typed authoring results. `Handle` remains reserved for
  live runtime objects such as `AppHandle`.
- A large file is acceptable when it has one coherent job. File size is evidence to
  inspect, not a reason to split by itself.

### 2.13 Desktop spawn bootstrap debt

Desktop inline scripts use an explicitly owned multiprocessing `spawn` context on
Windows, macOS, and Linux. A spawned interpreter imports the entry script before
entering its process target. The current launcher retains the source built during
that bootstrap in process-local state and consumes it when the script actor starts;
this prevents an expensive simulator model from being constructed and advanced
twice while preserving source authoring without a required Python main guard.
The source object does not cross a transport or pickle boundary.

This is contained runtime debt. The process-global handoff and its
`source`/`sources` tag dispatch are slightly clever, and the generic actor
launcher consequently knows more about source launch than its ideal contract
requires. They do not privilege a widget, backend, frontend, or operating system,
do not change canonical specs, and do not close any configuration-matrix row. A
future cleanup should replace the tagged handoff with a generic staged continuation
or move bootstrap coordination entirely into `_source_runtime.py`, without
reintroducing duplicate script execution or relying on POSIX-only `fork` behavior.

## 3. Standing coding principles

These are mandatory guardrails for this work, not retrospective review criteria.

1. **No widget privileged / first-class parity.** Built-in and third-party use one
   registry and one path; a built-in is a registered kind, not a blessed type. Do
   not dispatch with `isinstance` or closed type ladders. Shared machinery must not
   be named "builtin" or "extension" when it serves every registration.

2. **A widget is add/removable by touching only its own roughly one to three files.**
   Do not edit the frontend refresh loop, planner tables, or core kind constants.
   Search the new widget name, kind, and types across the tree: every hit outside
   its component, explicit composition root, tests, examples, or documentation is a
   possible privilege leak.

3. **Compose, do not bundle: one component, one job.** Producer to consumer through
   generic interfaces; output is plain data, not shaped for one specific consumer.

4. **No junk drawer.** Group by positive cohesion: the module is one nameable job.
   Do not group by residual labels such as `misc`, `utils`, `adapters`, or
   `leftovers`. Size is not the criterion. Before adding code, name the module's one
   job as a positive noun.

5. **Base over reuse-inheritance.** No false is-a relationships. When concrete
   implementations share a true contract, extract a shared base and make them
   siblings. Never inherit one concrete implementation from another merely to
   reuse code.

6. **Principled, not heuristic.** No band-aids. A fix must hold across the full
   configuration matrix, not only the current example. Name a temporary hack as
   such. Prefer relocating a concern to its owner over adding another special case.

7. **Core layering is strict.** Core never imports backends or frontends, even
   lazily. Inline authoring remains frontend-neutral. Kind strings plus registries
   are the seam between neutral authoring and a concrete frontend.

8. **Inline means no inheritance for user models.** A user's model stays a plain
   object handed to `cnv.*`; controls, recorders, and clicks use shared vocabulary.
   This does not prohibit legitimate library extension points such as the `Widget`
   ABC or backend bases used by low-level `RunSpec` authors.

9. **Widgets atomic, apps compose.** One widget owns one panel. Compose a complex
   interface from widgets, operators, contributions, and `cnv.layout`; do not make
   a library-level mega-widget. A local user class may wrap an app composition for
   reuse.

10. **Right-size complexity to context.** Do not carry library-grade abstraction
    into scratch or notebook code. Begin with the simplest honest data shape and
    add structure only when a concrete requirement demands it.

Workflow rule: inspect `git status` and recent history before offering to commit;
preserve unrelated user changes and remove obsolete paths instead of adding
pre-1.0 compatibility layers.

## 4. Implemented organization

The current tree combines feature-oriented first-party components with
responsibility-oriented infrastructure.

### 4.1 Neutral concrete geometries

`MorphologyGeometry` is not a widget. It lives with frontend-neutral concrete
geometry types while keeping the root `cnv.MorphologyGeometry` export:

```text
compneurovis/
  geometries/
    morphology.py
```

NEURON and Jaxley geometry modules remain simulator-local converters into this
type. A morphology widget component consumes it but does not own its identity.

### 4.2 First-party components

Each component package co-locates a built-in's authoring and frontend
implementation without importing the frontend from its authoring module:

```text
compneurovis/components/
  surface/{authoring.py, data.py, renderer.py, axes.py, vispy.py}
  morphology/{authoring.py, cylinders.py, renderer.py, vispy.py}
  line/{authoring.py, vispy.py}
  bar/{authoring.py, vispy.py}
  network2d/{authoring.py, vispy.py}
  grid_slice/{authoring.py, overlay.py, vispy.py}
  level_marker/{authoring.py, vispy.py}
```

Package `__init__.py` files remain lightweight. The Vispy first-party bootstrap
is the only registration path that imports the first-party `vispy.py` modules,
and it invokes every component's named registration callback explicitly.

### 4.3 Core

The small canonical vocabulary modules remain explicit. Do not merge `field.py`,
`references.py`, `values.py`, `messages.py`, and the canonical-spec modules
into a generic contracts file.

- Validation is separate from `core/app_spec.py` in `app_validation.py`.
- Actor execution machinery is grouped under `core/runtime/`: actors, hosts, launchers,
  bus, channel, runtime app, run functions, handle, options, and performance code.
- `RunSpec`, messages, app specs, fields, references, projections, and other
  canonical data contracts remain outside the runtime implementation package.
- `DiagnosticsSpec` remains a canonical data contract; process-local diagnostics
  behavior must not leak into it.

### 4.4 Inline

- `inline/app.py` owns the reusable mutable `InlineApp` composition object.
- `inline/authoring.py` owns the module-level ambient app and the public
  `source`/`layout`/`show` facade; `inline/__init__.py` only composes exports.
- `inline/sources/` separates source API/lowering, typed controls/actions/values,
  and concrete source variants.
- `inline/widgets/api.py`, `inline/widgets/source_api.py`, refs, compiler, and data
  producers remain separate coherent jobs.
- Widget, control, and action registry modules contain registration state and
  collision rules. First-party facades and registration composition live
  elsewhere.

### 4.5 Vispy

- Surface, Morphology, GridSlice, and LevelMarker renderer code lives with its
  component rather than in a residual frontend layer folder.
- Registry contracts are grouped under `frontends/vispy/registries/` without merging
  unrelated registries into a mega-registry.
- `frontends/vispy/builtins.py` is the one explicit first-party Vispy bootstrap.
  Registries themselves never import built-ins.
- `PanelManager` owns panel construction, lifecycle,
  layout, visibility, and sizing.
- `AppUpdateProcessor` owns message compaction,
  projection mutation, and production of refresh work.
- The Qt window owns the Qt shell, delegation, and top-level events.
- Plot2D is a shared host/capability substrate used by sibling Line and Bar
  renderers. Neither concrete renderer inherits the other.
- The controls panel, XY pad, first-party control renderers, and controls host
  lifecycle have positively named modules.
- Generic binding resolution lives in `frontends/vispy/bindings.py`; the residual
  `view_inputs` folder is gone.

### 4.6 Simulator backends

Simulator packages retain simulator-specific adapters:

```text
backends/
  startup.py
  compartment/history.py
  neuron/
    backend.py
    geometry.py
    layout.py
    source/{api.py, declarations.py, runtime.py, recording.py}
    io/{swc.py, sections_json.py}
  jaxley/
    backend.py
    geometry.py
    layout.py
    source/{api.py, declarations.py}
    io/swc.py
```

The exact number of files follows cohesion, not symmetry. Jaxley should not gain
empty layers merely to resemble NEURON.

- `geometry.py` stays with its simulator and converts native structures into
  neutral morphology geometry.
- `source/api.py` owns `cnv.neuron.source(...)` or `cnv.jaxley.source(...)` and
  simulator-specific authoring conveniences.
- Simulator morphology declarations obtain native geometry and optimized data
  from their backend, then attach the ordinary component-level `Morphology`
  widget with `GeometryRef` and `DataRef`.
- `source/runtime.py` owns the private source-aware backend joining generic inline
  bindings to native optimized execution.
- The low-level `NeuronBackend` and `JaxleyBackend` remain directly usable through
  `RunSpec`.
- The ambiguous simulator `inline.py` modules were dissolved. Generic widget
  declarations live in components; simulator-specific authoring stays in each
  simulator source package.
- `utils/` was replaced with positive `io/` and `layout.py` owners. SWC
  construction of NEURON sections or Jaxley cells remains simulator-specific.

NEURON and Jaxley now share canonical retention resolution and selected-entity
history state through `backends/compartment`. Native stepping and collection
remain simulator-local, especially NEURON pointer-vector sampling and Jaxley
compiled stepping.

Two ownership leaks were removed during that extraction:

1. `FieldRetentionSpec` now carries a generic producer requirement authored by a
   consumer. Backends resolve required sample capacity without knowing the consumer
   is Line.
2. Neutral backend-produced `StartupData` now lives in `backends/startup.py`;
   inline compilation consumes it without reversing the dependency.

### 4.7 Experimental notebook frontend

The notebook package now has explicit owners:

```text
frontends/vispy/notebook/
  builtins.py
  frontend.py
  host.py
  rfb_widget.py
  registries.py
  renderer.py
  runtime.py
```

`runtime.py` owns explicit placement and routes. `host.py` owns only notebook
event-loop polling. `renderer.py` owns one generic out-of-kernel raster actor.
`frontend.py` wraps the ordinary `VispyFrontendWindow`, so panel mounting,
operator resolution, contributions, refresh planning, and third-party Vispy plugin
discovery stay on the same registered path as desktop. Every non-control panel is
projected generically to a notebook raster canvas from its lifecycle inspection
surface or Qt widget; no Surface, Morphology, Line, or other widget kind is named
by notebook topology. Neutral controls and actions receive notebook-native
presentations from the open registries in `registries.py`; first-party ipywidget
implementations are registered from `builtins.py` through those same contracts.

Notebook raster projection still renders Vispy panels locally, but live rendering
defaults to one same-machine subprocess so OpenGL refresh and JPEG encoding cannot
block kernel control interaction. Field updates go to that actor and only compressed
frames return to the shell. Every raster panel uses the same `anywidget` remote
framebuffer. Its browser canvas acknowledges a sequence only after decoding and
painting it. The renderer performs no initial capture until that canvas mounts,
then keeps at most three unpainted frames across the app. This bounds Jupyter comm
traffic without tying the transport to JupyterLab or to a particular widget kind.
Notebook source actors initialize immediately so their initial AppSpec and fields
can render, but active ticks remain behind a runtime execution gate until every
initial raster panel has been painted. This preserves authored simulation timing:
frontend startup cannot silently consume an early stimulus, and examples do not
need to shift experimental events to compensate for UI load time.

Raster service is also registered, not dispatched by kind inside the scheduler.
`register_frame_policy(kind, target_hz=..., priority=..., max_inflight=...,
raster_scale=..., jpeg_quality=...)` gives built-in and third-party view kinds
the same experimental notebook contract. An authored positive `max_refresh_hz`
remains a hard ceiling. Logical panel size stays owned by layout and independent
from physical frame resolution. The first-party morphology policy requests a
higher continuous cadence and a short pipeline at native resolution. Line plots
reuse their registered PyQtGraph host but capture at two physical pixels per
logical pixel and higher JPEG quality; no notebook-specific Line renderer or
contribution path currently exists. Browser paint acknowledgements remain the
final capacity constraint, so a slow client reduces actual rate instead of
accumulating an unbounded queue.

Alternative rendering routes remain an intended extension seam, not rejected
architecture. A neutral authored view must not require one rendering library or
transport. A frontend may register multiple presentation routes where useful:
reuse a live Qt/Vispy host and rasterize it, render through another local engine
such as Matplotlib/Agg, or eventually use a browser-native renderer. Route
selection belongs to explicit frontend configuration and registered capabilities,
not to source authoring, widget-specific runtime actors, or conditionals added to
`cnv.show()`.

Any alternative route must preserve the complete panel contract. It must declare
which host and contribution capabilities it supports, consume the same neutral
AppSpec data and values, and never silently omit overlays, selection behavior, or
third-party contributions. When a preferred route cannot satisfy a panel, the
frontend must use a registered complete fallback or raise a precise capability
error. First-party routes must register through the same public contract available
to third parties. This keeps renderer choice recoverable and swappable without
sacrificing generic authoring or creating parallel widget semantics.

Notebook interactivity must also return. The raster framebuffer is a transport,
not a declaration that notebook panels are permanently passive. A complete
interactive route should carry normalized pointer, wheel, keyboard, resize, and
gesture events back to the renderer that owns the panel. That enables registered
camera orbit/pan/zoom, entity picking and selection, and Plot2D navigation without
moving interaction semantics into notebook-specific widget code. Input support
must be capability-declared per rendering route, ordered with frame presentation,
and subject to the same bounded backpressure rules as output. A static route may
remain useful, but it must advertise that limitation explicitly rather than
silently dropping authored interaction.

The explicit in-kernel option is diagnostic. All child processes start before
kernel Qt/OpenGL initialization for Windows, macOS, and Linux lifecycle safety.
The renderer selects the same instancing-capable PyQt6 `gl+` backend as desktop;
Vispy's default `gl2` wrapper breaks any first- or third-party instanced visual.

This remains experimental rather than alpha-supported. Raster projection does not
yet provide desktop-equivalent 3-D camera or picking interaction, layout parity,
or release hardening. Those are frontend capability gaps, not reasons to restore
widget-specific actors or a separate authoring model.

## 5. Execution record

The work proceeded as behavior-preserving vertical moves with obsolete imports
removed before continuing:

1. Establish the neutral geometries package and move `MorphologyGeometry`.
2. Create component packages, beginning with LevelMarker or GridSlice, then migrate
   Morphology, Surface, Network2D, Line, and Bar one at a time.
3. Establish the Vispy registries package and single first-party bootstrap.
4. Split Plot2D, Controls, panel lifecycles, and the desktop frontend coordinators.
5. Reorganize inline session/source code and relocate `StartupData`.
6. Extract shared compartment runtime behavior and reorganize NEURON/Jaxley source
   packages without weakening their optimized native paths.
7. Split `app_spec` validation and group core runtime implementation files.
8. Mechanically package the legacy notebook host, JupyterLab, and RFB code.
9. Replace that legacy topology with a generic notebook shell and generic renderer:
   frontend-local RunSpec placement, shared registered Vispy lifecycles, open
   ipywidget control/action presentation registries, and one paint-acknowledged RFB
   for every raster panel. Remove the obsolete special actors, environment forks,
   JupyterLab host, and morphology-specific RFB host.
10. Remove the remaining desktop privilege leaks: independent LevelMarker
    authoring, generic custom control hosts, host-independent control/action
    renderer contexts, targeted panel-host remounting, and geometry-neutral entity
    metadata.
11. Split inline app state from its module-level facade; open action authoring;
    make contributions panel-addressed; separate geometry-scoped click interactions
    from optional selection state; and generalize host inspection surfaces.
12. Remove final hidden singleton state and failure shortcuts: make simulator
    selections/widget fields instance-safe, resolve operator graphs recursively,
    validate contribution ownership, require explicit runtime topology, surface
    actor/bus failures, and preserve authoritative queue transitions.

Do not combine all moves into one unreviewable rename. After every component or
infrastructure slice, run its focused tests and the architecture grep before moving
the next owner.

## 6. Acceptance gates

- A component kind appears only in its component, explicit composition roots,
  tests, examples, and documentation.
- Core contains no built-in widget kind/type dispatch and imports no backend or
  frontend.
- Inline imports no concrete frontend.
- Backend/headless lowering imports no renderer or GUI package.
- Public registry modules contain contracts, collision rules, state, and lookup,
  but no first-party implementation imports.
- Built-ins, adjacent scripts, and installed plugins use the same registration
  calls.
- Canonical specs remain data-only, kind-keyed, fragment-safe, and transportable.
- Two instances and two fragments do not collide in ids, values, selections,
  operators, contributions, or refresh targets.
- Removing a plugin yields a precise unsupported-kind or missing-plugin error and
  does not disturb other components.
- A custom panel host need not imitate first-party viewport or controls inspection
  properties, and a patch to one custom panel remounts only that lifecycle.
- A third-party controls host can own built-in and third-party typed controls, and
  their renderers communicate only through public render contexts.
- A third-party action kind can be authored on a source or any `ControlsRef`, and
  no action id is assigned special behavior by frontend or runtime plumbing.
- A viewless capable panel can own a visual contribution; contribution refresh
  routing does not depend on `panel.view_ids[0]`.
- An interactive layer identifies an authored click role. Click handling, optional
  selection mutation, and renderer-specific selection presentation remain
  independent, and entity inspection follows the exact authored geometry even
  when ids overlap.
- A third-party geometry can provide pick/inspection metadata without a
  kind-specific frontend branch.
- Source-level, low-level `RunSpec`, static, live, and replay authoring remain
  expressible; unimplemented configuration-matrix rows are not structurally closed.
- The complete automated release gates pass. GUI checks run outside the sandbox.

Validation commands remain those in the repository `AGENTS.md`, including the
golden pytest suite, compileall, Poetry validation/build, strict MkDocs build, and
the documented manual GUI examples.

## 7. Deferred adjacent directions

These are not part of the physical organization pass, but the organization must not
block them:

- app-wide adaptive presentation admission, tracked in the
  [Adaptive Presentation Scheduler proposal](proposals/adaptive-presentation-scheduler.md);
- frontend selection/profiles and a documented frontend-role protocol;
- WebSocket transport and remote `serve`/`remote` authoring;
- fragment composition across transport seams and future N:M routing;
- notebook promotion work: interactive 3-D input, layout parity, and release
  hardening over the generic frontend path;
- standard logging and structured performance telemetry;
- a headless frontend/drive surface that exercises exactly the same lowering path;
- runtime control reconfiguration through canonical patches;
- an origin-neutral sampling contract only when a real use case can state cadence
  and retention semantics precisely.

These broader items remain sequenced by [Design Directions](design-directions.md),
the [Roadmap](roadmap.md), and the [Backlog](backlog.md). They must reuse the
canonical authoring and interaction boundaries recorded here rather than reopening
widget privilege.
