---
title: Building a Widget — walkthrough, pain points, and guardrails (handoff)
summary: A self-contained handoff for continuing the widget de-privileging work. (1) An end-to-end trace of building a new widget from scratch today (2-D and 3-D, third-party and built-in). (2) The isolated pain points, including the structural "widget-as-package" direction that pulls the authored per-widget specs out of core. (3) A current-source audit of additional gaps and misleading partial-parity tests. (4) The programming guardrails to hold while doing it. Feeds widget-taxonomy-proposal.md Phases 4 & 6.
status: handoff
date: 2026-08-05
---

# Building a Widget — handoff

**Who this is for:** the next contributor (human or agent) continuing the widget
de-privileging effort. It answers four things: how you build a widget *today*, where
the process is *still broken*, what a direct audit of current `src/` reveals beyond
the initial walkthrough, and the *principles* to hold while fixing it.

**Context:** the codebase is deep into taxonomy Phase 6 — every view kind
(`line_plot`/`bar_plot`/`surface`/`morphology`/`network2d`) is now an extension widget,
the refresh planner holds zero widget-kind knowledge, render-configs live with their
frontend impls (not core), and camera is off `PanelSpec`. See
[widget-taxonomy-proposal.md](widget-taxonomy-proposal.md) for the full history. What
The neutral public geometry, operator, and scoped-selection primitives now exist; what
remains is completing the external conformance target, converging renderer contracts, and
removing the built-ins' remaining special source paths.

The original widget seam is proven by
[Third-Party Widget Conformance Target](third-party-widget-conformance-proposal.md).
The active continuation—open panel hosts, Scene3D layers, controls as widgets,
registered control kinds, and independently owned overlays—is
[Panel, Control, and Visual-Contribution De-privileging](panel-control-layer-deprivileging-proposal.md).

A widget has **two layers** joined only by a `kind` string:

- **Authoring** (frontend-neutral, `inline/`): a `Widget[Ref]` that `declare`s an
  `ExtensionViewSpec(kind=…)` + its data, through `WidgetAuthoringContext`.
- **Rendering** (per-frontend, `frontends/vispy/`): a host/visual registered under
  the same `kind`, that draws the view.

Plus an optional third concern: **named exposure** (`src.<name>(...)` sugar).

The pass/fail question (taxonomy Phase 4): *could a third party author the widget
touching only its own files?* Trace it and the gaps fall out.

---

## 1. End-to-end walkthrough (current state)

### 1A. Minimal 2-D widget (the clean path) — e.g. a `gauge`

1. **Authoring class** — `gauge.py` (an adjacent app file is enough):
   ```python
   @dataclass(frozen=True, slots=True)
   class Gauge(Widget[PanelRef]):
       name: str
       read: Callable[[], float]
       def declare(self, context) -> PanelRef:
           data = context.data(self.name, read=self.read, labels=("v",))
           return context.view("gauge", self.name, inputs={"value": data},
                               properties={"vmin": 0.0, "vmax": 1.0})
   ```
   Public primitives only: `context.data` / `series` / `grid`, then `context.view`.

2. **Rendering host** — `gauge_vispy.py`:
   ```python
   class GaugeHost(QtWidgets.QWidget):
       def __init__(self, *, panel_id, view_id, title): ...
       def refresh(self, view, inputs, properties, values): ...   # draw
   ```
   `properties` arrive with bindings already resolved; `inputs` names → field ids.

3. **Register the renderer in one frontend callback:**
   ```python
   def register():
       register_renderer("gauge", GaugeHost)
   ```
   An app-local author records that callback with
   `register_vispy_plugin("gauge_vispy:register")`. This stores only an import
   string; Qt/Vispy is imported later in the frontend process. An installable
   distribution may expose the same callback through the
   `compneurovis.vispy_plugins` entry-point group.

4. **(optional) Named exposure** — `register_widget("gauge", Gauge)` (dynamic, untyped),
   or a typed proxy method on `SourceWidgetAPI` (built-in). Either way `src.add(Gauge(...))`
   already works, fully typed.

5. **Refresh** — the extension host is the framework refresh unit. Its
   `refresh(...)` method may diff and optimize internally, but the public SDK does not
   advertise custom 2-D target names that the frontend cannot dispatch.

**Third-party 2-D verdict: clean.** One CompNeuroVis install plus ordinary app-local
files is sufficient. Packaging and entry points are optional deployment conveniences.

### 1B. 3-D widget — what's *extra* (e.g. a volume renderer)

Everything in 1A, `context.view(..., panel_kind=PANEL_KIND_VIEW_3D)`, **plus**:

1. **Visual class** — `refresh_for_target(kind, view, ctx)`, `clear()`,
   `pick_entity(xf, yf, canvas)`; optional `wants_selection(view)` /
   `refresh_overlays(host, view, ctx)` capability hooks.
2. **One `register_3d_visual(...)` call** — it requires the factory,
   `from_extension` config builder, ordered targets, and patch schema; value-binding
   and field-replacement routing are optional arguments on that same call.
3. **Discovery** — the same deferred callback mechanism as 2-D:
   `register_vispy_plugin("module:register")` for app-local files or
   `compneurovis.vispy_plugins` metadata for an installed distribution.

### 1C. Adding an operator (e.g. a slice) — the deep end

Author: `context.operator(kind, name, inputs=..., geometries=..., properties=...,
contributes_to=...)` returns ordinary `DataRef` output. Data and geometry dependencies
are explicit scoped refs in the neutral operator envelope. GridSlice and the external
PointCloudPlaneSlice both use this path directly.
Render: `ExtensionOperatorSpec` dispatches through
`register_operator_adapter(kind, adapter)`; typed interpretation stays frontend-local.
The adapter resolves output through `OperatorResolveContext`, which exposes fields,
geometries, values, and fragment identity without exposing the frontend window.

### 1D. Adding scoped entity selection

Declare selection as its own interaction state, associate it with a geometry, and explicitly
attach it to the view that owns picking:

```python
geometry = context.geometry(
    "point_cloud",
    f"{self.name}_geometry",
    data={"positions": positions, "entity_ids": entity_ids},
)
selected = context.selection(
    f"{self.name}_selection",
    geometry=geometry,
    initial=(),
    multiple=self.select_multiple,
)
panel = context.view(
    "point_cloud_3d",
    self.name,
    geometries={"points": geometry},
    selections={"entities": selected},
)
```

`SelectionRef` is ordinary bindable scoped state. The view-to-selection association tells
the frontend which selection owns a pick; `EntityClicked(selection_id, entity_id)` plus
the fragment route tells the backend exactly which state may change. Single/multiple toggle
semantics are shared by the frontend and all backends. There are no process-wide selected
entity keys and no morphology-specific selection mode.

---

## 2. Pain points

### 2A. Tactical (ranked)

| # | Pain | Where | Fix direction |
|---|---|---|---|
| **1** | **Closed: one discovery callback for app-local and installed widgets.** `register_vispy_plugin("module:register")` defers ordinary files; installed distributions use `compneurovis.vispy_plugins`. Both 2-D renderers and 3-D visuals register inside that callback. | public Vispy plugin SDK | Keep the callback frontend-only and out of canonical specs. |
| **2** | **Closed: 3-D configuration is explicitly required.** `register_3d_visual` requires `from_extension`; camera/background configuration can no longer be silently omitted from the registration. | 3-D registration surface | Preserve this as one complete declaration. |
| **3** | **Closed: 3-D uses one registration call.** Factory, config builder, ordered targets, patch routing, bindings, and field replacement are one collision-checked contract. | `register_3d_visual` | Do not re-expose the internal component registries. |
| **4** | **Closed at the public boundary: discovery no longer differs by dimension.** The same plugin callback may call `register_renderer`, `register_3d_visual`, and `register_operator_adapter`. Built-in bootstrapping remains internal. | `plugins.py` | Built-ins ship in the CompNeuroVis wheel and require no separate installs. |
| **5** | **Accepted: typed `src.<name>` requires editing `SourceWidgetAPI`.** Third-party named exposure is dynamic/untyped via `register_widget`; `src.add(Widget())` stays fully typed. | `source_api.py` | Documented Python-typing tradeoff, not a blocker. |

**Headline:** public geometry, geometry-aware operator authoring/output, installed 3-D
discovery, the external package boundary, and scoped selection have landed. The separately
installed fixture now includes PointCloud3D, PointCloudPlaneSlice, and Scatter2D. It lowers
headlessly, crosses a spawned pipe, keeps instances/fragments independent, routes one bound
control change to both a 3-D slab overlay and ordinary projected 2-D data, and discovers both
renderers from package metadata. The maintainer confirmed the real rendered
control/overlay/scatter path. The conformance seam and pre-migration authoring gate are
proven; remaining work is built-in migration through that stable path.

### 2B. Structural direction: cohesive widget components (not separate installs)

A separate, deeper issue than the tactical list — and the north star that dissolves
several pains at once.

**Symptom.** A handful of *authored* per-widget specs still live in `core/`:
`LevelMarker` and `MorphologyGeometrySpec`. They are not
universal kit — they are specific to one widget each. The former `GridGeometrySpec`
was deleted once surface grid coordinates were made field-owned.

**Why they're stuck.** These specs are *authored* (created in `inline/` / `backends/`)
**and** *rendered* (`frontends/`). A built-in widget is **exploded across those sibling
trees** — its authoring in `inline/widgets/`, its frontend in `frontends/vispy/`. Two
siblings' only shared ancestor is `core`, so their shared authored type is *forced* into
core. (Render-configs escaped core this session precisely because they are frontend-only,
never authored — they had no such pull.)

**Why a third party doesn't have this problem.** A third-party widget is a
**self-contained component**: its typed declaration objects + frontend implementations
co-live in one place.
Those declarations lower to core-owned, kind-keyed neutral extension envelopes; no
per-widget Python spec class needs to enter core or cross the canonical app boundary.

**The fix.** Structure built-in widgets the same way — **self-contained internal
components**, each
owning its typed authoring declarations + frontend implementations, discovered uniformly,
and lowering through neutral extension specs. Then:
- `core` = **pure kit**: kind-keyed extension specs, `AppSpec`/`Field`/bindings — the
  language-neutral vocabulary every widget builds on, with **no** per-widget specs.
- The typed authored specs (`LevelMarker` and morphology geometry)
  leave core or become package-local declaration values.
- This also removes the remaining special built-in source paths and discovery divergence:
a widget component co-locates its public authoring + self-registration.

Here "component" or the older shorthand "widget-as-package" describes code cohesion,
not Python distribution boundaries. Built-ins remain inside the single CompNeuroVis
wheel and need no separate install. User widgets may be ordinary adjacent scripts, as
proved by `examples/extensions/local_gauge`; packaging is optional when distribution
or reuse calls for it.

**Do not** move these specs to the frontend *without* the restructure — that makes the
authoring layer import rendering (a `core`-layering violation, see guardrails). The
restructure is the prerequisite. Large, cross-cutting; its own effort.

### 2C. App-configuration-matrix correction

The [App Configuration Matrix](../app_configuration_matrix.md) is a hard constraint on this
work. The earlier idea that a third party could put a package-owned `GeometrySpec` or
`OperatorSpec` subclass in `AppSpec` is sufficient for the current Python/pickle T2 path,
but not for Unity, Web, remote WebSocket, or bespoke non-Python frontends. Requiring those
consumers to import a Python widget class would silently close valid matrix rows.

The corrected boundary is:

- package-owned: typed declaration objects, validation helpers, Vispy/notebook/Unity/Web
  renderer implementations;
- canonical: core-owned, kind-keyed, data-only extension envelopes and scoped references;
- frontend-local: discovery and renderer registration for the kinds that frontend supports;
- runtime: interactions routed through the catalog so Full, Observer, and Partial roles can
  be enforced without widget-specific authority logic.

This does **not** require every widget package to implement every renderer. It requires the
authored structure to be renderer-neutral, transport-neutral, fragment-safe, usable by
live/replay/static/external producers, and lowerable through the same `AppSpec`/`RunSpec`
path for inline, low-level, and bespoke authoring. Pickle round-tripping remains a T2 test,
not the public extension contract.

The executable gates and topology-by-topology preservation rules live in
[Third-Party Widget Conformance Target](third-party-widget-conformance-proposal.md).

### 2D. Current-source audit — what is complete, what only looks complete

This section records a direct audit of the current implementation after the initial
walkthrough above. It is intentionally stricter than the proposal status labels: the
question is not whether a representation or planner test is generic, but whether an
installed third-party widget can author, lower, discover, render, refresh, and interact
through the same end-to-end path as a built-in.

**Validation snapshot (2026-08-06):** `poetry run python -m pytest -q` passes all 42 tests.
The audit findings below have now either landed or been converted into explicit,
tested boundaries before built-in migration.

#### The milestone that has genuinely landed

- Every built-in view kind (`line_plot`, `bar_plot`, `surface`, `morphology`,
  `network2d`) is authored as `ExtensionViewSpec(kind=...)`.
- Typed render-configs are frontend-local reconstruction values, not authored core
  view types.
- Refresh planning is kind/registry-driven; the planner contains no built-in widget
  kind table.
- Camera configuration is off generic `PanelSpec` and owned by 3-D view config.
- The taxonomy renames and producer splits are complete.

This is real progress: the old privileged **view representation** has been removed.
It is not yet full third-party **widget authoring**, because declaration, source
bookkeeping, discovery, and host dispatch still contain privileged paths.

#### The proposal overstates authoring parity

`widget-taxonomy-proposal.md` says the authoring half of one-path is complete because
`context.grid(...)` plus `context.view(panel_kind=...)` can reproduce a miniature
surface-shaped field and panel. That benchmark omits the parts that make the real
surface/morphology/grid-slice widgets demanding:

- `Surface` still uses `_register_surface` and `_declare_grid_field`.
- `GridSlice` now uses public `context.operator` and generic panel contributions.
- `Morphology` uses the public scoped-selection primitive, but still uses
  `_register_geometry` and `_register_morphology`.
- `InlineSourceBase` still owns special `_surfaces`, `_geometries`,
  and morphology/surface collections, then splices them into compilation/runtime
  separately.

Therefore the accurate statement is: **uniform authored view representation is done;
the public authoring vocabulary is not.** The Phase-4 capability benchmark does not pass
until the real built-ins can be expressed through public primitives and those special
source collections disappear.

Do not mechanically publish the private methods. Public primitives should express
generic concepts (geometry, operator output/contribution, scoped selection), own id
allocation, and be usable by built-ins and third parties alike. A public
`register_surface` would merely rename the privilege.

#### Additional rendering and discovery audit — closed before migration

1. **2-D refresh promise corrected.** Ordinary extension panels are standalone
   QWidgets and `"extension"` is their complete, dispatched refresh target. The
   planner-only `register_view_refresh_schema` API is no longer public. A host may
   optimize internally during `refresh(...)`; the framework does not promise
   sub-widget target dispatch.

2. **Panel-host boundary made explicit.** Core validation remains frontend-neutral
   and accepts arbitrary panel kinds, preserving the configuration matrix. Vispy
   deliberately implements `extension`, `view_3d`, and `controls`; an unknown
   kind now raises a precise error instead of silently disappearing. `extension`
   means any standalone QWidget, not merely a 2-D plot.

3. **Relevant-only 3-D construction landed.** `create_3d_visuals()` instantiates
   only the visual claimed by the panel's primary view kind. Installing a plugin
   cannot allocate visuals in unrelated panels.

4. **3-D target collisions are rejected.** A second visual cannot claim a target
   already owned by another visual; duplicate or conflicting registrations fail
   deterministically.

5. **The public registration family is cohesive.**
   `compneurovis.frontends.vispy` exports `register_renderer`,
   `register_3d_visual`, `register_operator_adapter`, and
   `register_vispy_plugin`. One deferred callback can register all contributions
   before planning and panel construction; internal config/schema registries are not
   separate author obligations.

6. **The 3-D visual protocol is enforced.**
   `refresh_for_target(...)`, `clear()`, and `pick_entity(...)` are required and
   validated when a factory constructs a visual. `wants_selection(...)` and
   `refresh_overlays(...)` remain explicitly optional capability hooks.

#### Scoped selection — implemented

`SelectionSpec` is a neutral, data-only interaction declaration associated with one
geometry. Public `context.selection(...)` returns a scoped `SelectionRef`, and views
declare the exact selections they own. Picking is view-scoped;
`EntityClicked(selection_id, entity_id)` is fragment-routed; inline, NEURON, and Jaxley
backends update only that declared selection. Single/multiple click policy is shared.

The external conformance fixture proves two selectable point clouds with overlapping entity
ids remain independent, and composed fragments may reuse the same local selection id without
colliding. Morphology now uses the same primitive. The private `_selection_modes` path and
global selected-entity value keys have been deleted.

The maintainer confirmed the ordinary two-panel desktop smoke: clicking a point turns it
yellow only in the panel that owns its selection. Scoped selection therefore passes both
the automated isolation gates and the real frontend interaction check.

#### Surface grid geometry duplication — resolved

`GridGeometrySpec` was constructed only by `Surface` and repeated the dimensions and
coordinates already present on the surface field. It has now been deleted: surface scene
data reads field coordinates directly, and grid-slice overlay matching is field-based.
The public geometry primitive can therefore focus on genuine geometry such as morphology.
Preserve a distinct geometry only where it carries information the field cannot.

#### Recommended sequence after the audit

1. **Migrate Surface through the proven public primitives.** GridSlice already uses the
   neutral operator path; remove Surface's remaining private registration/collection path
   without introducing a compatibility layer.
2. **Migrate morphology geometry to a neutral extension envelope.** Preserve simulator-owned
   construction and optimized sampling while deleting the typed core geometry and private
   source registration path.
3. **Preserve the closed renderer contract while migrating.** App-local and installed
   discovery, collision checks, relevant-only mounting, one-call 3-D registration, honest
   extension refresh, and precise host-family errors are now the migration baseline.
4. **Do cohesive widget-component restructuring after each built-in reaches the public
   seam.** Otherwise the restructure merely moves
   current special cases into new directories and makes the eventual public API harder to
   change.
5. **Converge controls separately.** Ordinary control panels and extensible control kinds remain
   important, but they should not obscure completion of the widget authoring/rendering path.

---

## 3. Guardrails — the programming principles to hold

These are the standing design principles for this codebase. Apply them *proactively*,
not only when something breaks. (Distilled from the maintainer's stated guidance.)

1. **No widget privileged / first-class parity.** Built-in and third-party use **one**
   registry and one path; a built-in is a *registered kind*, not a blessed type. No
   `isinstance`/`type` dispatch anywhere — dispatch by registered kind. *Naming corollary:*
   never name shared machinery "builtin"/"extension"; a getter that returns *all* registered
   things is not a "builtin" getter.

2. **A widget is add/removable by touching only its own ~1–3 files.** ZERO edits to the
   frontend refresh loop, the planner tables, or core kind constants. *Acceptance check
   (run it):* grep the new widget's name/kind/type across the tree — **every hit outside its
   own files is a privilege leak.** A type reference is clean only when a module registers
   its *own* type; a shared file naming another widget's type is the smell.

3. **Compose, don't bundle — one component, one job.** Producer → consumer via generic
   interfaces; a component's output is plain data, not shaped for one specific consumer.

4. **No junk drawer.** Group by *positive cohesion* (the module IS one nameable job), never
   by a negative/residual property ("not-refresh", misc, utils, adapters, "leftover X").
   **Size is not the criterion, cohesion is** — a large file is fine when everything serves
   one concept; before adding to a module, name its one job as a positive noun.

5. **Base over reuse-inheritance.** No false is-a. When two things share code, extract a
   shared **base** and make the divergences **siblings** (e.g. native vs extension over one
   visual) — never inherit one concrete thing from another for reuse.

6. **Principled, not heuristic.** No hacks/band-aids; a fix must hold across the *full*
   scenario matrix, not the case in front of you. Name a hack a hack. Fix the **root cause**
   — which is often "relocate the concern to where it belongs," not add a special case.

7. **Core layering is strict.** `core` never imports backends or frontends (even deferred).
   Authoring (`inline`) is frontend-neutral. The `kind` string + the registries are the only
   seam between neutral authoring and a concrete frontend.

8. **Inline = no inheritance (user models).** A user's model stays a plain object handed to
   the widget/`cnv.*`; wire controls/recorders/clicks via shared vocabulary, **not** by
   subclassing library backend classes. (This is about *user models*; the `Widget` ABC and
   the registries are legitimate library extension points.)

9. **Widgets atomic, apps compose.** One widget = one panel. A "complex widget"
   (spectrogram = surface + slice + playhead) is **composed in the app** and wrapped in a
   *local user class* if reuse is wanted — never a library-level composed widget. Flexibility
   comes from operators contributing visuals into a primary view, and from `cnv.layout`
   composing panels.

10. **Right-size complexity to context.** Don't carry library-grade abstraction into
    scratch/notebook code; start from the simplest data shape (often a dict) and add
    structure only when concretely demanded.

*Workflow:* before offering to commit, check `git log`/`status` — the maintainer usually
has already committed.

---

## 4. Where to start (picking this up)

Do not migrate `Surface` yet. The point-cloud fixture exposed a deeper composition
boundary: `view_3d` is privileged only because it owns a shared canvas, controls
are still a special singleton panel, and independently authored overlays are still
drawn by their target widgets.

Proceed through the active panel/control/layer proposal:

1. Move the complete Vispy panel lifecycle behind an open registry.
2. Make Scene3D an ordinary registered host with scene-layer capabilities.
3. Make Controls an ordinary multi-instance widget with explicit ownership.
4. Register neutral control kinds and migrate built-ins.
5. Move PlaneSlice/GridSlice and LevelMarker graphics to owning layer contributors.
6. Then migrate Surface and morphology through those public composition paths.

Hold the §3 guardrails throughout — especially the grep acceptance check (guardrail 2) and
no-junk-drawer (guardrail 4), which are the two most often violated mid-refactor.
