---
title: Widget Authoring Architecture and Refactor Record
summary: Current widget-extension architecture, the completed de-privileging refactor, standing coding principles, and the active package-organization plan.
status: active architecture record
date: 2026-08-06
---

# Widget Authoring Architecture and Refactor Record

This is the source of truth for CompNeuroVis widget authoring and the continuing
package-organization refactor. It replaces the completed widget-taxonomy,
third-party-conformance, panel/control/layer, and building-a-widget proposals. It
also retains the still-relevant direction from the older Authoring Layer proposal.

The implementation in `src/` remains authoritative. This record explains why its
boundaries exist, what the completed refactor proved, and what physical cleanup is
still required.

## 1. Current outcome

The behavioral de-privileging work is complete:

- Every built-in view lowers to `ExtensionViewSpec(kind=...)`; core contains no
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
- Scene and plot additions use `VisualContributionSpec`; the component that authors
  a slice or marker owns its graphical contribution. Its target renderer does not
  branch on the contributor kind.
- Selection is explicit, scoped, fragment-safe interaction state. Two widgets may
  use overlapping entity ids without sharing selection.
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

A Vispy plugin callback registers whichever independent capabilities it provides:

- `register_renderer(...)` for an ordinary extension QWidget;
- `register_panel_host(...)` for a new host lifecycle;
- `register_scene_layer(...)` for content mounted in Scene3D;
- `register_operator_adapter(...)` for frontend-side operator resolution;
- visual-contribution renderers for Scene3D or Plot2D additions.

The callback is frontend-only. Canonical lowering and backend execution must work
without importing it.

### 2.5 Intentional asymmetries

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

The target combines feature-oriented first-party components with
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

Co-locate each built-in's authoring and frontend implementation without importing
the frontend from its authoring module:

```text
compneurovis/components/
  surface/{authoring.py, vispy.py, renderer.py, axes.py}
  morphology/{authoring.py, vispy.py, renderer.py}
  line/{authoring.py, vispy.py}
  bar/{authoring.py, vispy.py}
  network2d/{authoring.py, vispy.py}
  grid_slice/{authoring.py, vispy.py}
  level_marker/{authoring.py, vispy.py}
```

Package `__init__.py` files remain lightweight. The Vispy first-party bootstrap is
the only code that eagerly imports the `vispy.py` modules.

### 4.3 Core

Keep the small canonical vocabulary modules explicit. Do not merge `field.py`,
`references.py`, `values.py`, `messages.py`, and the extension-envelope modules
into a generic contracts file.

- Extract validation from `core/app_spec.py` into `app_validation.py`.
- Group actor execution machinery under `core/runtime/`: actors, hosts, launchers,
  bus, channel, runtime app, run functions, handle, options, and performance code.
- Keep `RunSpec`, messages, app specs, fields, references, projections, and other
  canonical data contracts outside the runtime implementation package.
- Split `DiagnosticsSpec` from process-local diagnostics configuration if necessary
  to preserve this boundary.

### 4.4 Inline

- Move the mutable `InlineApp` session and module-level accumulator out of
  `inline/__init__.py`; the initializer should export public names only.
- Turn `inline/sources.py` into a source package separating base state/lowering,
  typed control/action/value authoring, and concrete local/composed/remote variants.
- Keep `WidgetAuthoringContext`, refs, compiler, and data producers separate; they
  are large but cohesive.
- Keep registry modules implementation-free. Built-in control/widget facades and
  bootstrapping live in explicitly named implementation or composition modules.
- Remove the unused duplicate `InlineSourceBase._initial` helper.

### 4.5 Vispy

- Replace the layer-oriented scattering of Surface, Morphology, GridSlice, and
  LevelMarker with their component packages.
- Group registry contracts under `frontends/vispy/registries/` without merging
  unrelated registries into a mega-registry.
- Use one explicit first-party Vispy bootstrap instead of separate renderer and
  panel-host bootstraps. Registries themselves never import built-ins.
- Extract a `PanelManager` from `frontend.py` for panel construction, lifecycle,
  layout, visibility, and sizing.
- Extract an `AppUpdateProcessor` from `frontend.py` for message compaction,
  projection mutation, and production of refresh work.
- Keep the Qt window responsible for the Qt shell, delegation, and top-level events.
- Split Plot2D into a shared canvas/capability substrate and sibling Line and Bar
  renderers. Neither concrete renderer inherits the other.
- Split the controls panel, XY pad, built-in control renderers, and controls host
  lifecycle into positively named modules.
- Move generic binding resolution out of the residual `view_inputs` folder once its
  feature modules have moved.

### 4.6 Simulator backends

Simulator packages retain simulator-specific adapters:

```text
backends/
  startup.py
  compartment/{runtime.py, history.py}
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
- Source-level, low-level `RunSpec`, static, live, and replay authoring remain
  expressible; unimplemented configuration-matrix rows are not structurally closed.
- The complete automated release gates pass. GUI checks run outside the sandbox.

Validation commands remain those in the repository `AGENTS.md`, including the
golden pytest suite, compileall, Poetry validation/build, strict MkDocs build, and
the documented manual GUI examples.

## 7. Deferred adjacent directions

These are not part of the physical organization pass, but the organization must not
block them:

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
canonical extension and interaction boundaries recorded here rather than reopening
widget privilege.
