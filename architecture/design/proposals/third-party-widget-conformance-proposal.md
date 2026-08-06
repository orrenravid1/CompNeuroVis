---
title: Third-Party Widget Conformance Target
summary: Drive full third-party widget authoring with one separately packaged PointCloud3D + PointCloudPlaneSlice + Scatter2D implementation, using vertical end-to-end slices and deletion gates rather than publicizing current private hooks.
status: active proposal
date: 2026-08-06
---

# Third-Party Widget Conformance Target

## Decision

CompNeuroVis will finish widget de-privileging against one concrete external-package
target rather than by generalizing internal classes in isolation.

The target package is `cnv-pointcloud-demo`, containing:

- `PointCloud3D`: a 3-D point-cloud widget with live scalar values and scoped entity
  selection;
- `PointCloudPlaneSlice`: a plane/slab operator that contributes an overlay to its
  point-cloud panel and produces projected 2-D point data;
- `Scatter2D`: a 2-D scatter widget that consumes the slice output as ordinary data.

The package is a conformance fixture, not a proposed CompNeuroVis built-in. Its job is
to prove that an installed third party can express a demanding widget using only stable
public contracts. Built-ins then migrate through the same contracts and their privileged
paths are deleted.

This proposal operationalizes the remaining work identified by
[Building a Widget](building-a-widget.md) and the terminal goal in
[Widget Taxonomy and Uniformity](widget-taxonomy-proposal.md).

## 1. Target application

The final authoring shape should be equivalent to:

```python
import compneurovis as cnv
from cnv_pointcloud import PointCloud3D, PointCloudPlaneSlice, Scatter2D

src = cnv.source(step)

cloud_a = src.add(PointCloud3D("Cloud A", positions=a_xyz, read=read_a))
cloud_b = src.add(PointCloud3D("Cloud B", positions=b_xyz, read=read_b))

cut = src.add(
    PointCloudPlaneSlice(
        "Cloud A slice",
        source=cloud_a,
        axis=axis,
        position=position,
        thickness=thickness,
    )
)
scatter = src.add(Scatter2D("Slice", source=cut))

cnv.layout(
    (
        (cloud_a, cloud_b),
        (scatter, src.controls_panel),
    )
)
cnv.show()
```

Exact signatures remain subject to implementation evidence. The important contracts are:

- two point-cloud instances coexist;
- each owns independent selection state;
- the slice output is ordinary data, not scatter-specific data;
- the scatter is a separate consumer;
- moving the slice controls refreshes both its 3-D overlay and 2-D output;
- no CompNeuroVis shared module knows the point-cloud kind or classes.

## 2. Why this target

The target crosses every material unfinished boundary:

| Capability | Proof |
|---|---|
| Public declaration | The package uses only public context primitives. |
| Custom geometry | Point positions, entity ids, and labels lower into a neutral, kind-keyed geometry spec. |
| Live data | Point scalars update through ordinary field production. |
| 3-D rendering | A package-owned visual renders in the shared 3-D host. |
| 2-D rendering | A package-owned scatter host uses the ordinary extension-host path. |
| Scoped interaction | Selecting Cloud A cannot mutate Cloud B. |
| Operators | The plane slice emits data and contributes a 3-D overlay. |
| Composition | The slice and scatter remain separate atomic components. |
| Discovery | Installed entry points load every frontend contribution. |
| Transport | Neutral extension specs cross the real actor/process boundary without Python class identity. |
| Refresh | Default refresh is correct; registered surgical targets dispatch end to end. |

A simpler gauge would not exercise geometry, operators, selection, or 3-D discovery. A
surface clone would bias the public API toward the current implementation and would not
prove that a genuinely new topology can participate.

## 3. Spatial slicing: shared concept, sibling implementations

`GridSlice` and `PointCloudPlaneSlice` are the same high-level operation: intersect or
sample spatial data with a plane. They are not the same concrete algorithm or output.

| Concern | Dense grid / height field | 3-D point cloud |
|---|---|---|
| Input topology | Ordered rectilinear 2-D samples | Unstructured 3-D entities |
| Selection | Fix an axis coordinate or intersect a surface | Select a finite-thickness slab |
| Output | Ordered 1-D profile | Unstructured points projected into plane coordinates |
| Natural consumer | Line plot | Scatter plot |
| Numerical issue | Coordinate selection/interpolation | Distance tolerance and projection basis |

The implementations should eventually share:

- a plane definition (axis/position as a convenience over origin/normal);
- control bindings;
- operator contribution and refresh machinery;
- overlay ownership conventions;
- data-source output contracts.

They must retain separate topology-specific validation, sampling algorithms, output
schemas, and renderer-specific overlay drawing.

Grid slicing now lowers through `ExtensionOperatorSpec(kind="grid_slice")` and the public
operator contribution primitive; it no longer has a typed core spec or private source
collection. Do not turn that neutral envelope into a mode-heavy point-cloud operator. Build
the point-cloud implementation as a sibling first. Only then extract a shared immutable
plane value from demonstrated common
structure. A user-facing `PlaneSlice` facade is justified only if dispatch is open and
registry-driven by source capability; an `if grid / elif point_cloud` ladder fails the
proposal.

## 4. Architectural decisions

### 4.1 Context owns identity

Generated field, geometry, operator, view, panel, selection, and value keys belong to the
authoring context. A third-party declaration supplies a local name and package-owned data,
not hand-assembled globally unique ids.

The public design must not expose `SpecBinding`, `_add_binding`, source collection mutation,
or a generic `context.contribute(...)` escape hatch. Those would make AppSpec construction
public vocabulary instead of providing widget-authoring primitives.

### 4.2 Data references name data sources

An operator output and a stored field are both valid view inputs. Today `DataRef._field_id`
also carries operator ids. The public contract must name the concept honestly (data source),
while internal resolution distinguishes stored and computed sources.

Do not make every consumer branch on field versus operator. Resolution occurs at the view
input boundary, once.

### 4.3 Selection is scoped interaction state

Selection is no longer process-wide magic keys. A selection declaration owns a stable
scoped identity, its geometry/view association, initial value, single/multiple policy, and
a returned `SelectionRef`.

Picking events must carry enough ownership context to route a click. Two target instances
are the non-negotiable test; a single-instance demo can hide global-state defects.

### 4.4 Widget kinds are open; host families are deliberate

This effort targets third-party widgets inside supported host families: ordinary extension
hosts and shared 3-D canvases. It does not assume that any arbitrary `panel_kind` string has
a renderer. Either panel-host families become explicitly registerable in a later proposal,
or validation documents them as a closed infrastructure taxonomy.

Novel widget kinds must never require novel panel kinds.

### 4.5 Registration is public, discovered, and collision-safe

A third-party frontend package needs one documented import surface. Registration must happen
before panel construction and refresh planning, work in every frontend process, and reject
duplicate claims deterministically.

Installing a new visual must not instantiate it in unrelated panels. Refresh-target names
must either be scoped by their owning renderer or checked globally for collisions.

### 4.6 Refresh has an honest baseline

Blanket refresh is the safe default and requires no author schema. Surgical refresh is
optional, but is supported only when the frontend actually dispatches the registered target
to a renderer method. Planner-only tests do not establish rendering support.

### 4.7 Implementations are package-owned; canonical specs are neutral

The widget declaration, validation helpers, and renderer implementations belong to the
widget package. Their lowered identity must not depend on a package-owned Python subclass.
That would work for a pickled T2 Python process, but it would make Unity, Web, remote
WebSocket, and other non-Python consumers unable to interpret the canonical app.

Geometry and operator authoring therefore lower to kind-keyed, language-neutral extension
envelopes, symmetric with `ExtensionViewSpec`. The concrete target is an
`ExtensionGeometrySpec` and `ExtensionOperatorSpec` (or an equivalently neutral wire
schema) containing only ids, registered kind strings, references, immutable properties, and
declared inputs/outputs/contributions. A package may expose richer typed declaration objects
to its Python authors, but package classes and callbacks cannot enter `AppSpec`.

Frontend adapters dispatch by registered kind, never `isinstance` or imported package
class. Transport codecs may optimize the representation, but every codec must preserve the
same neutral meaning.

Built-in widget packaging happens after these public seams stabilize. Moving current special
cases into directories earlier would reorganize privilege rather than remove it.

### 4.8 The app configuration matrix is a hard constraint

The widget structure must preserve every row of the
[App Configuration Matrix](../app_configuration_matrix.md). This does not mean every widget
package must ship a renderer for every frontend. It means the authored app remains valid and
transportable independent of renderer placement, while each frontend may register support
for the same widget kind or report that the kind is unsupported.

The invariants are:

| Matrix dimension | Widget-system requirement |
|---|---|
| Backend/frontend environment | `AppSpec` contains no GUI objects, process-local callbacks, or Python package type identity. Discovery runs in the process that hosts a renderer. |
| Renderer | Authoring is renderer-neutral. Vispy, notebook, Unity, Web, and headless implementations claim the same kind through frontend-local registries. |
| Transport | In-process, pipe, future WebSocket, and shared-memory codecs carry the same neutral specs and scoped refs. Pickle success is necessary for T2, not the public contract. |
| Topology | All ids and interactions remain fragment/actor scoped; registries do not become per-app singleton state, and multiple widget instances/backends cannot collide. |
| Interaction role | Rendering works without mutation. Commands travel through the interaction catalog so Full, Observer, and Partial roles can be enforced outside the widget. |
| Data source | Live, replay, static, and external producers feed the same field/data-source refs. Widgets do not own simulators or assume ticks exist. |
| Authoring API | Inline declarations lower into the same canonical `AppSpec`/`RunSpec` used by low-level and bespoke apps; no source-only runtime bypass is permitted. |

Topology preservation is checked explicitly:

- **T1/T2/T3:** the same widget declaration lowers through the current canonical run path;
  T2 additionally proves process transport, and T3 must not require a desktop-only host.
- **T4:** no canonical object requires importing Python widget classes on the remote
  frontend; a future WebSocket codec can encode it by kind and data.
- **T5:** an Observer can render the widget without registering mutation handlers.
- **T6/T7:** fragment-scoped data, selection, and operator refs remain unambiguous when
  several actors contribute instances of the same kind.

An unimplemented matrix row is not a release requirement for this refactor, but the design
must remain expressible and each implemented slice must add no assumption that closes it.

## 5. Delivery slices

Each slice is end-to-end and must leave the suite green. No phase adds a parallel compatibility
path.

### Slice 0 — remove misleading grid geometry — **Done**

`GridGeometrySpec` is constructed only by `Surface` and duplicates dimensions/coordinates
already stored on its field. `surface_scene_from_field` already supports reading field coords
directly.

- Make surface rendering and grid-slice overlay matching field-based.
- Remove surface `geometry_id` and `SurfaceRef.geometry_id`.
- Remove `GridSliceOperatorSpec.geometry_id`.
- Delete `GridGeometrySpec` and its public exports if no consumer remains.
- Prove non-default coordinates and grid-slice refresh/output remain intact.

This prevents the new public geometry API from being designed around redundant grid state.

### Slice 1 — conformance package and import boundary — **Done**

- Create a separately packaged fixture under `examples/extensions/cnv_pointcloud_demo/`.
- Give it its own `pyproject.toml`, import package, and entry points.
- Add an import-boundary check: its declaration layer may import only public neutral
  authoring/spec APIs, while its Vispy layer may additionally import the public Vispy plugin
  SDK. Neither may import private names or internal frontend modules.
- Introduce the neutral extension geometry/operator envelopes before the target needs them;
  the fixture must not place a package-defined class in `AppSpec`.
- Add a subprocess/install smoke so discovery is exercised as distribution metadata, not a
  direct test import.
- Add a headless lowering smoke with no renderer entry point loaded, proving renderer
  discovery is a frontend concern rather than an authoring/backend dependency.

The initial package may be a failing conformance fixture only on a dedicated development test;
the golden suite must remain green until the required public slice lands.

### Slice 2 — static PointCloud3D walking skeleton — **Done**

Implement the smallest complete path:

```text
external Widget
    -> public geometry/data/view primitives
    -> AppSpec
    -> installed entry-point discovery
    -> one relevant 3-D visual
    -> rendered panel
```

This slice establishes public geometry declaration/ref identity, the public frontend
registration surface, 3-D discovery, and lazy/relevant visual construction. The same static
declaration must lower in T1, survive the actual T2 pipe serialization boundary, and remain
valid when no frontend renderer is installed. No selection or operators yet.

Implementation evidence:

- the separately installed distribution authors and lowers the static view without importing
  its Vispy module;
- the neutral `AppSpec` crosses a spawned multiprocessing pipe and the receiving process
  verifies that no `cnv_pointcloud_demo` declaration class was imported;
- installed entry-point discovery mounts only the `point_cloud_3d` visual;
- `tests/pointcloud_gui_smoke.py` constructs the real Vispy host and rendered a non-empty
  643 × 945 RGBA frame with the package-owned markers visual;
- `tests/pointcloud_desktop_smoke.py` launches `demo.py` through the ordinary public
  `cnv.show()` desktop runtime for the maintainer-facing release check.

The maintainer confirmed the ordinary `cnv.show()` desktop smoke: the external cloud
rendered and the window exited cleanly after being closed.

### Slice 3 — scoped selection

**Done.**

- `SelectionSpec` and public `context.selection(...)` provide neutral,
  fragment-scoped selection identity and `SelectionRef` state.
- Views explicitly associate selection refs with their geometry refs.
- Picking supplies the owning view; `EntityClicked(selection_id, entity_id)` plus the
  fragment route reaches exactly one backend selection.
- Single/multiple click policy is shared across the frontend, inline, NEURON, and Jaxley
  backends.
- Two point-cloud instances with overlapping entity ids are independent, and two composed
  fragments may reuse the same local selection id without collision.
- Morphology uses the same selection primitive; `_selection_modes` and process-wide
  selected-entity keys are gone.

Automated gates cover neutral lowering, backend authority, cross-fragment composition, and
package-owned pick decoding. The maintainer also confirmed the ordinary two-panel desktop
smoke: clicking a point turns it yellow only in the panel that owns its selection.

### Slice 4 — PointCloudPlaneSlice plus Scatter2D

- Add the public operator declaration/output contract.
- Make the plane slice attach its overlay without mutating another widget's binding.
- Produce projected 2-D point data with explicit coordinate/attribute schema.
- Render that data through the separately authored `Scatter2D` consumer.
- Prove control changes refresh overlay and scatter through the real frontend.

### Slice 5 — migrate GridSlice and Surface

- Move `GridSlice` onto the same public operator infrastructure. **Done.**
- Move `Surface` entirely onto public grid/view/operator-panel primitives.
- Delete `_register_surface`, `_surfaces`, and the
  corresponding special compilation paths.
- Extract a shared plane value only where the two working slice implementations demonstrate
  identical structure.

### Slice 6 — registration and refresh hardening

- Consolidate the documented plugin SDK.
- Make duplicate kind/target behavior consistent.
- Complete 2-D partial-target dispatch before advertising it.
- Make required 3-D visual methods an actual protocol.
- Test missing plugins, duplicate registrations, unrelated panels, and coarse fallback.

### Slice 7 — built-ins become packages

Co-locate each built-in's typed authoring declarations, frontend implementations, and
self-registration. Lower their authored state through the same neutral extension specs.
Remove `LevelMarker` and morphology-specific geometry specs from core once no canonical
path depends on their Python type identity. `GridSliceOperatorSpec` has already been deleted.

Control panels and extensible control kinds remain a separate convergence proposal.

## 6. Acceptance gates

### External-package gate

- `rg "point_cloud|pointcloud" src/compneurovis` returns no framework-owned knowledge of the
  plugin kind or types.
- The target installs and is discovered from entry-point metadata.
- Removing it yields a precise missing-plugin error and does not affect built-in panels.
- Canonical specs survive the real process transport without importing target-package
  declaration classes.

### Authoring gate

- The target imports no private authoring machinery.
- Context allocates all ids.
- `src.add(...)` is fully typed; named `src.<widget>` exposure remains optional.
- No public API is named for surface, morphology, grid slice, or point cloud.

### Interaction gate

- Two selectable target instances do not share state.
- Single/multiple policy is per selection declaration.
- Click routing is fragment-safe and identifies its owner.

### Operator/composition gate

- Plane-slice output is ordinary `DataRef` data.
- Scatter consumes it without point-cloud or operator awareness.
- Grid slice and point-cloud slice share infrastructure but not topology branches.

### Rendering gate

- Installing the plugin does not construct its visual in unrelated 3-D panels.
- Default refresh works without a schema.
- Every registered surgical target reaches a renderer entry point in an end-to-end test.
- Duplicate registration and target collisions fail deterministically.

### Configuration-matrix gate

- The external target lowers through the same `AppSpec`/`RunSpec` path for inline and
  low-level authoring; it introduces no source-only runtime path.
- Its canonical geometry, views, operators, selections, and contributions are kind-keyed,
  data-only, fragment-scoped, and free of GUI objects, callbacks, and Python subclass identity.
- Static data renders without a simulation, and live/replay/external producers use the same
  data-reference contract.
- A headless/backend process can lower and transport the app without importing a concrete
  renderer.
- Observer rendering does not require mutation authority; all mutations remain catalogued
  interactions that future Full/Observer/Partial role enforcement can filter.
- Two fragments may contribute the same widget kind without id, selection, operator, or
  refresh-target collisions.
- Each delivery slice records which matrix rows were executed and why all unimplemented rows
  remain expressible.

### Deletion gate

The work is not complete while any replaced privilege remains:

- `_register_surface`, `_register_morphology`, `_register_geometry`;
- `_surfaces` and `_geometries` special source paths;
- all-visuals-in-all-3-D-panels mounting;
- planner-only partial-refresh claims;
- built-in authored specs in core after widget packaging.

## 7. Non-goals

- Shipping point cloud or scatter as built-in alpha widgets.
- A universal computational geometry framework.
- Automatic dispatch implemented as closed type/kind ladders.
- Arbitrary new panel-host families in this effort.
- Control-kind extensibility or multiple control panels.
- Compatibility layers for pre-1.0 private hooks.
- Moving built-ins into packages before the conformance seam is proven.

## 8. Progress record

- **2026-08-06:** Proposal opened. Target settled as PointCloud3D +
  PointCloudPlaneSlice + Scatter2D, with grid and point-cloud slicing treated as sibling
  implementations of spatial slicing.
- **2026-08-06:** Slice 0 landed. Surface coordinates now have one owner (the field),
  grid-slice matching is field-based, and `GridGeometrySpec` plus surface/grid-slice
  `geometry_id` plumbing were deleted. The matrix audit found no narrowed row: coordinates
  remain canonical field data for live, replay, static, and external producers, and the
  T1/T2 transport path is unchanged. Slice 1 is next.
- **2026-08-06:** The app configuration matrix became an explicit acceptance gate. This
  corrected the earlier Python-only assumption: implementations remain package-owned, but
  canonical extension identity is neutral and kind-keyed so T4-T7, Unity, Web, and bespoke
  frontends remain expressible.
- **2026-08-06:** Slice 1 completed. Core now provides strict language-neutral
  `ExtensionGeometrySpec` and `ExtensionOperatorSpec` envelopes, public context geometry and
  operator declarations, explicit view geometry refs, context-owned instance namespaces,
  and generic panel contributions. The separately packaged fixture installs into an isolated
  target, lowers headlessly without importing its renderer, survives the T2 serializer, and
  is discovered from real distribution entry-point metadata.
- **2026-08-06:** GridSlice migrated early to the public operator primitive. Its typed core
  spec, private binding/collection, surface mutation hook, and type-keyed frontend dispatch
  were deleted. Vispy plugin discovery and relevant-only 3-D visual mounting landed; the
  static PointCloud3D authoring and visual implementation exist.
- **2026-08-06:** Slice 2 implementation completed. A real spawned pipe carries the neutral
  app without importing package declaration types, and the separately installed Vispy plugin
  mounted and rendered a non-empty frame. The normal `cnv.show()` desktop smoke is packaged
  as a one-command manual check; the maintainer ran it successfully, completing Slice 2.
- **2026-08-06:** Slice 3 implementation landed. Neutral `SelectionSpec` declarations,
  explicit view ownership, fragment-routed `EntityClicked(selection_id, entity_id)`, and
  one shared single/multiple policy now span the frontend and all three backend families.
  The external fixture proves independent same-fragment instances and colliding local ids
  across composed fragments; morphology migrated and the global/private selection path was
  deleted. This exercises T1 directly and T2 transport/routing, while preserving T4-T7:
  canonical state is data-only, mutation stays in the interaction catalog, and all ids are
  fragment-scoped. The maintainer confirmed independent two-panel point highlighting,
  completing Slice 3.
