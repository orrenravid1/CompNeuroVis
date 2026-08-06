---
title: Panel, Control, and Visual-Contribution De-privileging
summary: Replace Vispy panel branches, privileged control kinds, and host-owned operator overlays with registered hosts and capability-specific child renderers.
status: implemented
date: 2026-08-06
---

# Panel, Control, and Visual-Contribution De-privileging

## Decision

The completed PointCloud conformance work proved neutral widget declarations,
frontend-only discovery, scoped interactions, and computed data. It also exposed
three remaining forms of privilege that must be removed before built-in migration:

1. Before Slice A, Vispy constructed `extension`, `view_3d`, and `controls`
   panels through a hardcoded branch.
2. Controls are collected into one implicit panel and rendered through closed
   value-spec and presentation-kind ladders.
3. Independently authored overlays are drawn by the target widget instead of by
   the component that owns the overlay.

The target is an open composition model:

```text
neutral PanelSpec.kind
        |
        v
registered frontend panel host
        |
        +-- optional capability-specific child renderers
              +-- scene layers
              +-- plot layers
              +-- control items
```

Dimensionality is not a panel privilege. A standalone extension QWidget may render
2-D, 3-D, text, tables, images, or anything else. Shared 3-D infrastructure remains
useful only as an ordinary registered `Scene3D` host that owns a canvas, camera,
picking, and layer composition.

## 1. Authoring targets

### 1.1 Named widget sugar remains open

`register_widget("name", WidgetFactory)` continues to provide
`source.name(...)` through the same `source.add(...)` funnel. Dynamic methods
are runtime-typed; built-in static typing may be supplied as declarations over the
same runtime registry, not as a second implementation path.

### 1.2 Controls panels are widgets

The canonical shape is explicit panel ownership:

```python
simulation = source.controls("Simulation")
speed = simulation.slider(...)
gain = simulation.number(...)

display = source.controls("Display")
palette = display.dropdown(...)

cnv.layout(((plot,), (simulation, display)))
```

More than one controls panel is valid. Adding a control to one panel must not add it
to another. A default controls panel may remain convenience sugar only if it delegates
to the same ordinary `Controls` widget.

### 1.3 Control kinds are registered

Control extensibility has two independent surfaces:

- authoring registration, analogous to `register_widget`;
- frontend item rendering, keyed by the neutral presentation kind.

Illustrative API:

```python
register_control("knob", Knob)
register_control_renderer("knob", KnobRenderer)
```

The canonical control value declaration must be a core-owned, kind-keyed, data-only
envelope. Package-owned Python value-spec subclasses cannot enter `AppSpec`.
Built-in slider, spinbox, checkbox, dropdown, text, XY-pad, and button presentations
register through the same renderer path. Actions/buttons are included; hotkeys are a
related input-binding extension point and may use a sibling registry.

## 2. Panel hosts

### 2.1 Open frontend registry

Vispy panel construction dispatches exclusively through a public collision-safe
registry keyed by `PanelSpec.kind`. The frontend window contains no panel-kind
ladder.

A panel-host registration owns the complete lifecycle it requires: construction,
refresh routing, visibility, teardown, and any presentation cadence. A registry that
only replaces the construction branch while leaving refresh hardcoded does not pass.

### 2.2 Built-in hosts use the public path

The initial registered Vispy hosts are:

- standalone view host: creates the QWidget registered for the primary view kind;
- `Scene3D`: owns the shared canvas/camera/picking/layer lifecycle;
- `Controls`: owns control-item layout and action presentation.

These are CompNeuroVis built-ins in the one distribution. They are not core constants
or privileged frontend branches.

### 2.3 Scene3D replaces the privileged 3-D view

`PANEL_KIND_VIEW_3D` and `register_3d_visual` were migration-state APIs and are
now removed. Scene content registers as capability-specific layer renderers:

```text
Scene3D host
    +-- PointCloud layer
    +-- Surface layer
    +-- PlaneSlice layer
    +-- selection layer
    +-- renderer-private axes/chrome
```

A self-contained 3-D widget that does not need shared composition may remain a normal
standalone QWidget renderer.

## 3. Visual contributions and ownership

Anything independently authored or contributed by another component lowers to a
neutral visual-contribution envelope. Renderer-private implementation details do not.

Candidate canonical shape:

```python
VisualContributionSpec(
    id=...,
    kind="plane_slice_layer",
    target=...,
    inputs={...},
    geometries={...},
    selections={...},
    properties={...},
)
```

The exact name is decided by implementation evidence, but the invariants are fixed:

- target identity is explicit and fragment-scoped;
- the contribution contains only neutral data and refs;
- the owning package registers its layer renderer;
- the target host advertises a narrow capability such as `scene3d.layers/v1` or
  `plot2d.layers/v1`;
- the target widget never imports or branches on contributor kinds;
- unsupported capability/kind pairs fail precisely.

Do not create one universal rendering escape hatch. Registries belong only at open,
heterogeneous composition boundaries. Atomic QWidget widgets need no internal registry.

## 4. PlaneSlice ownership

The data dependency remains:

```text
PointCloud -> PlaneSlice -> projected Field -> Scatter
```

PlaneSlice owns its computation and every graphical contribution derived from that
computation. It may present a slab on the source Scene3D host and, when explicitly
targeted, decoration on a compatible Plot2D host. Scatter consumes only the projected
field and knows nothing about PlaneSlice.

The target host must expose a generic layer capability, but it must not reserve a
PlaneSlice-specific slot or implement PlaneSlice-specific drawing.

GridSlice follows the same rule. The two slice algorithms remain siblings unless their
completed implementations prove a genuinely identical lower-level primitive.

## 5. Plot overlays

`LevelMarker` is independently authored plot content and therefore cannot remain a
plot-specific Python class in core or a hardcoded `Plot2DPanel` branch. It becomes a
neutral Plot2D layer contribution with a registered renderer.

Axes, tick labels, legends, and colorbars may remain renderer-private when they are
intrinsic chrome of one renderer. If they become independently authorable, targetable,
or package-contributed, they cross the same visual-contribution boundary.

## 6. App-configuration-matrix constraints

This work must preserve every row in the
[App Configuration Matrix](../app_configuration_matrix.md):

- panel, control, and layer specs are core-owned neutral data;
- discovery occurs only in the rendering/authoring process that needs it;
- no Qt, Vispy, callbacks, or package-defined classes cross `AppSpec`;
- ids and targets remain fragment/actor scoped for composed sources;
- Observer frontends can render without mutation authority;
- other frontends may register different panel hosts and renderers for the same kinds;
- an unsupported frontend reports a missing renderer/capability without invalidating
  the neutral app.

## 7. Delivery slices

Each slice is end-to-end. No compatibility layer or parallel privileged path remains
after its migration.

### Slice A — registered panel-host lifecycle

**Status: implemented on 2026-08-06.** Vispy now exposes a collision-safe
`register_panel_host` contract. Registered lifecycle objects own construction,
refresh-target claiming and cadence, visibility, compact sizing intent, inspection
capabilities, and disposal. The frontend window performs generic lookup/dispatch only.
The app-local gauge fixture proves a new panel kind from two adjacent scripts with no
package install and no framework edit.

- Define the public collision-safe Vispy panel-host registration contract.
- Move construction, refresh routing, visibility, cadence, and teardown behind it.
- Register the current `extension`, `scene_3d`, and `controls` implementations
  through that path as ordinary entries.
- Delete the panel-kind branch from the frontend window.
- Prove a package-owned panel host without framework edits.

### Slice B - Scene3D as an ordinary capable host

**Status: implemented on 2026-08-06.** `scene_3d` is now only a neutral
registry key, not a core constant. Its lifecycle is an ordinary
`register_panel_host` entry, and authored 3-D content uses
`register_scene_layer`. The old `PANEL_KIND_VIEW_3D` and `register_3d_visual`
surfaces were removed rather than retained as aliases.

- Introduce the registered Scene3D host and neutral scene-layer capability.
- Migrate the current shared camera, picking, selection, overlay, and cadence behavior.
- Route both built-in and third-party 3-D contributions through the layer registry.
- Delete the privileged `view_3d` panel category and special 3-D visual API.
- Keep a standalone 3-D QWidget on the ordinary `extension` path.

### Slice C - Controls widget and multiple panels

**Status: implemented on 2026-08-06.** `source.controls(name)` returns an
ordinary `ControlsRef` panel widget with the same explicit typed methods as the
default source convenience. Controls and visible actions record their owner at
authoring time; the compiler no longer merges them into the first controls panel.
Core no longer exports or dispatches on a controls panel constant, and Vispy
handles `"controls"` as an ordinary registered host key. Automated coverage
proves two independent panels and canonical transport.

- Add the ordinary `Controls` widget/ref authoring surface.
- Make controls/actions explicitly owned by one panel.
- Remove the compiler's first-controls-panel merge and fixed-id assumption.
- Remove final-row and single-panel frontend assumptions.
- Prove two panels with independent values/actions and composed fragments.

### Slice D - open control kinds

**Status: implemented on 2026-08-06.** Core now carries only
`ControlValueSpec(kind, default, properties)` and
`ControlPresentationSpec(kind, properties)`. Public collision-safe
`register_control`, `register_control_renderer`, and
`register_action_renderer` paths own authoring and Vispy presentation.
Every built-in control and the built-in button registers through those paths.
Registered names appear as both `source.<name>(...)` convenience and
`source.controls(...).<name>(...)`; no untyped generic source method was added.
The third-party knob conformance test proves neutral lowering, explicit panel
ownership, transport, name collision handling, and renderer replacement rules.

- Replace the closed value-spec union with a neutral kind-keyed envelope.
- Add public authoring and frontend renderer registries.
- Migrate every built-in control presentation through the registry.
- Include action buttons; specify hotkey/input binding separately where necessary.
- Prove a third-party knob or color control through T1 and T2.

### Slice E - visual-contribution foundation

**Status: implemented on 2026-08-06.** Core carries the neutral,
fragment-scoped `VisualContributionSpec`; Scene3D and Plot2D advertise narrow
capabilities and dispatch contribution instances through collision-safe public
registries. Refresh planning addresses individual contribution ids and covers
field, operator-output, value, patch, and full-refresh dependencies.

- Add the neutral scoped visual-contribution envelope.
- Add Scene3D and Plot2D capability-specific layer registries.
- Make refresh targets address contribution instances, not global contributor names.
- Prove collision, missing capability, transport, and duplicate-fragment behavior.

### Slice F - PlaneSlice and GridSlice ownership

**Status: implemented on 2026-08-06.** GridSlice and the external PlaneSlice
fixture own both their data operators and their scene contributions. Surface
and PointCloud contain no slice-kind branches, overlay slots, or renderer
storage. The obsolete panel/operator attachment contract was deleted.

- Move plane/slab graphics from PointCloud and Surface renderers into their operator
  packages.
- Keep Scatter/Line as data consumers with no slice-kind knowledge.
- Delete target-renderer imports of slice kinds/configs.
- Confirm the existing GUI behavior manually.

### Slice G - LevelMarker

**Status: implemented on 2026-08-06.** `LevelMarker` is now an authoring-only
declaration lowered through `context.visual_contribution`. Plot2D discovers
the registered `level_marker` renderer and has no marker branch or marker
state. Core carries no LevelMarker type.

- Replace `LevelMarker` with a neutral Plot2D layer contribution.
- Register the built-in reference-line renderer through the public layer registry.
- Delete plot-specific marker identity from core and the hardcoded plot branch.

### Slice H - built-in migration

**Status: implemented on 2026-08-06.** Surface, Morphology, Line, and Bar now
declare exclusively through public context primitives. Their dedicated binding
classes and the special `_surfaces`, `_geometries`, and parallel binding
collections are gone. Morphology's typed `MorphologyGeometry` lives with the
widget and lowers to `ExtensionGeometrySpec(kind="morphology")`; Vispy
reconstructs it at the renderer boundary. NEURON and Jaxley keep the optimized
typed geometry internally while emitting only the neutral spec. Built-ins
remain part of the single CompNeuroVis installation.

- Migrate Surface and morphology through public fields, geometries, Scene3D layers,
  selections, and visual contributions.
- Remove private source collections and remaining core per-widget types.
- Co-locate built-in components without creating separate distributions.

## 8. Acceptance gates

- A new panel host touches only its package and registration callback.
- Two controls panels remain independent and layout normally in any row/column.
- A third-party control kind requires no core or frontend branch edit.
- PointCloud and Surface contain no PlaneSlice/GridSlice kind knowledge.
- Scatter and Line contain no slice kind knowledge.
- Plot2D contains no hardcoded independently authored layer kinds.
- A standalone 3-D QWidget needs no Scene3D path.
- Shared Scene3D composition retains camera, picking, selection, overlays, and cadence.
- Canonical specs cross the spawned T2 pipe without renderer imports.
- T6/T7-style duplicate local ids remain fragment-safe.
- The golden/release suite passes; GUI checks are run manually outside the sandbox.

## 9. Non-goals

- One mega-registry for unrelated extension points.
- Treating renderer-private implementation objects as public contributions.
- Requiring separate installs for built-ins or app-local widgets.
- Implementing every future Web/Unity renderer during this refactor.
- Preserving pre-1.0 privileged APIs after their replacement is complete.
