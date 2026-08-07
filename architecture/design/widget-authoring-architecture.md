---
title: Widget Authoring Architecture and Refactor Record
summary: Current widget authoring architecture, third-party registration contracts, implemented package ownership, standing coding principles, and known limitations.
status: active architecture record
date: 2026-08-06
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
- Selection is explicit, scoped, fragment-safe interaction state. Two widgets may
  use overlapping entity ids without sharing selection. Picks name the authored
  selection role, and entity metadata is resolved through that selection's exact
  geometry.
- GridSlice and point-cloud PlaneSlice are sibling spatial-slicing implementations.
  Their outputs are ordinary data consumed by Line or Scatter without consumer
  knowledge of the originating operator.
- Surface grid coordinates have one owner, the field. The redundant
  `GridGeometrySpec` path is gone.
- Surface, Morphology, Line, Bar, Network2D, and GridSlice author through the same
  public context primitives available to third parties.

The external `examples/extensions/cnv_pointcloud_demo` fixture proved the difficult
path end to end: PointCloud3D, a plane-slice operator and owned 3-D overlay,
projected Scatter2D output, controls, scoped picking, duplicate local ids across
fragments, spawned-process transport, installed plugin discovery, and real GUI
rendering. `examples/extensions/local_gauge` proves that an adjacent script can add
a custom panel host without a package install or framework edit.

The structural organization pass is now complete for the supported desktop/source
path. First-party components, registries, controls, panel lifecycles, desktop
coordinators, inline session/source responsibilities, core runtime machinery, and
simulator source/runtime/IO owners now have explicit package homes. The experimental
notebook files received the promised mechanical package move; replacing their
widget-specific actor topology remains deferred.

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
installed distribution is not required: `examples/extensions/local_gauge` proves
the adjacent-script form, while `cnv_pointcloud_demo` is packaged only to test
installed discovery.

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
| `operator(...)` | Kind-keyed computed data | `OperatorSpec`, output `DataRef` |
| `view(...)` | Kind-keyed view plus its owning panel | `ViewSpec`, `PanelSpec`, `PanelRef` |
| `visual_contribution(...)` | Owner-authored graphics in another panel capability | `VisualContributionSpec` |

Bindings nested in view, operator, and contribution properties lower to canonical
`ValueBindingSpec` values. Fields, geometries, selections, operators, views,
contributions, panels, and values are fragment-scoped during app integration.
Frontend renderers receive the resolved fragment-local resources rather than
reaching into a source or simulator.

`DataRef` intentionally describes only data identity plus useful authoring metadata
such as series dimension, selectors, and unit. It does not name a consumer.
`PanelRef` is layout identity. Specialized refs may expose several independent
capabilities: `MorphologyRef`, for example, exposes its panel, scoped selection,
and optional optimized selection-history data.

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

The current Vispy registration seams are:

| Registration | Responsibility |
|---|---|
| `register_renderer(kind, factory)` | Ordinary standalone QWidget host with `refresh(view, inputs, properties, values)` |
| `register_scene_layer(...)` | Typed Scene3D layer reconstruction, refresh schema, rendering, commit participation, and picking |
| `register_operator_adapter(kind, adapter)` | Operator dependency, binding, patch-impact, and output-field resolution |
| `register_scene_contribution(...)` | Contribution renderer for `scene3d.layers/v1` |
| `register_plot_contribution(...)` | Contribution renderer for `plot2d.layers/v1` |
| `register_panel_host(kind, lifecycle)` | Complete construction, refresh ownership, visibility, sizing, and disposal for a panel kind |
| `register_control_renderer(...)` | QWidget presentation for a control presentation kind |
| `register_action_renderer(...)` | QWidget presentation for an action kind |

All registries reject collisions unless their public contract explicitly permits an
intentional override. Missing renderer, host, contribution, or control support
raises a precise error including the live registered set.

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

Picking and inspection do not reconstruct a built-in geometry class. An
`GeometrySpec` opts into generic entity lookup by putting stable
`entity_ids` in `data`. Scalar arrays of the same length are exposed as
per-entity fields, and richer records may be declared under
`metadata["entities"][entity_id]`. Frontend interaction contexts resolve that
neutral structure for every registered geometry kind.

A selectable scene layer returns `EntityPick(selection_role, entity_id)`. The
frontend resolves `selection_role` through the authored view's `selections`
mapping, updates that exact `SelectionSpec`, and records it as the active
selection. `entity_info(..., selection=...)` then follows the selection's
`geometry_id`; it never scans geometries and accepts the first matching entity id.
This keeps multiple selectable roles in one view and duplicate ids across
geometries deterministic.

`MorphologyGeometry` writes its section, location, and label information into
this same neutral metadata shape. It remains a concrete geometry convenience, not
a widget and not a privileged frontend protocol.

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

Package `__init__.py` files remain lightweight. The Vispy first-party bootstrap is
the only code that eagerly imports the `vispy.py` modules.

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

### 4.7 Notebook deferral

The mechanical organization pass created:

```text
frontends/vispy/notebook/
  host.py
  jupyterlab.py
  rfb.py
```

The current hard-coded morphology and line render actors remain in `host.py`, and
notebook-specific RunSpec construction remains in `_source_runtime.py`. Both are
explicit deferred debt. The next notebook pass should move construction into this
frontend-local package and replace the special actors with registered
frontend-local render placements rather than polishing the special cases.

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
8. Mechanically package notebook host, JupyterLab, and RFB code while preserving
   behavior.
9. Deferred: replace notebook's widget-specific actor topology and source-runtime
   RunSpec construction with registered frontend-local placement.
10. Remove the remaining desktop privilege leaks: independent LevelMarker
    authoring, generic custom control hosts, host-independent control/action
    renderer contexts, targeted panel-host remounting, and geometry-neutral entity
    metadata.
11. Split inline app state from its module-level facade; open action authoring;
    make contributions panel-addressed; make picks selection-role-aware; scope
    entity lookup through selections; and generalize host inspection surfaces.

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
- A selectable layer identifies the authored selection role, and entity inspection
  follows that selection's exact geometry even when ids overlap.
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
- explicit runtime configuration replacing notebook environment flags;
- standard logging and structured performance telemetry;
- a headless frontend/drive surface that exercises exactly the same lowering path;
- runtime control reconfiguration through canonical patches;
- an origin-neutral sampling contract only when a real use case can state cadence
  and retention semantics precisely.

These broader items remain sequenced by [Design Directions](design-directions.md),
the [Roadmap](roadmap.md), and the [Backlog](backlog.md). They must reuse the
canonical authoring and interaction boundaries recorded here rather than reopening
widget privilege.
