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

The implementation target and phased acceptance gates are now owned by
[Third-Party Widget Conformance Target](third-party-widget-conformance-proposal.md).

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

1. **Authoring class** — `my_pkg/gauge.py`:
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

2. **Rendering host** — `my_pkg/gauge_host.py`:
   ```python
   class GaugeHost(QtWidgets.QWidget):
       def __init__(self, *, panel_id, view_id, title): ...
       def refresh(self, view, inputs, properties, values): ...   # draw
   ```
   `properties` arrive with bindings already resolved; `inputs` names → field ids.

3. **Register the renderer** — one of:
   - third-party: an entry point in the `compneurovis.vispy_renderers` group
     (`gauge = my_pkg.gauge_host:GaugeHost`). **Auto-discovered, zero library edits.**
   - built-in: add a line to `_register_builtin_renderers()` in `renderers/registry.py`.

4. **(optional) Named exposure** — `register_widget("gauge", Gauge)` (dynamic, untyped),
   or a typed proxy method on `SourceWidgetAPI` (built-in). Either way `src.add(Gauge(...))`
   already works, fully typed.

5. **(optional) Surgical refresh** — `register_view_refresh_schema("gauge", …)`. Skip it
   and any change blanket-repaints the host (correct, coarse).

**Third-party 2-D verdict: clean.** Own package only — entry point + `register_widget`.

### 1B. 3-D widget — what's *extra* (e.g. a volume renderer)

Everything in 1A, `context.view(..., panel_kind=PANEL_KIND_VIEW_3D)`, **plus**:

1. **Visual class** — `refresh_for_target(kind, view, ctx)`, `clear()`,
   `pick_entity(xf, yf, canvas)`; optional `wants_selection(view)` /
   `refresh_overlays(host, view, ctx)` capability hooks.
2. **`register_3d_visual(kind, factory, targets=(…))`** — declares the ordered refresh
   target kinds it renders (the frontend derives its dispatch tables from this).
3. **Typed render-config + `register_view_render_config(kind, SpecClass.from_extension)`**
   — in practice *required*, not optional (see pain #3): the frontend reads camera /
   background off the view by attribute, so a widget with no reconstructor silently
   loses them.
4. **Discovery** — installed packages expose a callable in the
   `compneurovis.vispy_plugins` entry-point group. The frontend loads it before refresh
   planning and panel construction.

### 1C. Adding an operator (e.g. a slice) — the deep end

Author: `context.operator(kind, name, inputs=..., properties=..., contributes_to=...)`
returns ordinary `DataRef` output. GridSlice now uses this path directly.
Render: `ExtensionOperatorSpec` dispatches through
`register_operator_adapter(kind, adapter)`; typed interpretation stays frontend-local.

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
| **1** | **3-D discovery is now public; registration remains wider than 2-D.** Installed packages load through `compneurovis.vispy_plugins`, but a 3-D plugin still commonly makes several registration calls. | public Vispy plugin SDK | Consolidate only after the point-cloud fixture shows which fields belong together. |
| **2** | **3-D rendering assumes a typed render-config; 2-D takes a dict.** A 2-D host gets resolved `properties`. A 3-D visual gets a reconstructed typed spec, and the frontend reads `camera_*`/`background_color` via `getattr(view, …)` — so skipping `register_view_render_config` silently drops those to defaults. "Optional" reconstruction is effectively mandatory. | `frontend.py::_refresh_view_3d_if_due`, `render_config.py` | Make the 3-D refresh contract take `properties` like the 2-D one (or truly optional reconstruction). |
| **3** | **3-D is ~3 registrations to 2-D's one** (`register_3d_visual` + `register_view_render_config` + usually `register_view_refresh_schema`, plus a render-config class). | 3-D registration surface | Fold render-config + targets into one `register_3d_visual(...)`; keep the refresh schema the only separate opt-in. |
| **4** | **Built-in discovery differs by dimension** — 2-D built-ins are a `register_renderer` block; 3-D built-ins are bottom-of-module `from . import surface, morphology`. Legitimate exception ("a loader lists its built-ins"), but two mechanisms. | `renderers/registry.py`, `view3d/visuals.py` | One discovery convention (ideally entry points, self-referential for built-ins) for both. |
| **5** | **Typed `src.<name>` requires editing `SourceWidgetAPI`** (shared file); third-party named exposure is dynamic/untyped via `register_widget`. | `source_api.py` | Accepted Python-typing tradeoff — documented, not a defect. `src.add(Widget())` stays typed for everyone. |

**Headline:** public geometry, operator authoring, installed 3-D discovery, the external
package boundary, and scoped selection have landed. The separately installed PointCloud3D
fixture now lowers headlessly, crosses a spawned pipe, mounts only its relevant visual,
renders a real Vispy frame, and gives two instances independent selection state. Its normal
desktop launch is retained as an explicit manual check. PointCloudPlaneSlice + Scatter2D is
the next vertical capability slice; remaining registration/refresh items are frontend
convergence work.

### 2B. Structural direction: widget-as-package (why authored specs are stuck in core)

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

**Why a third party doesn't have this problem.** A third-party widget is a **self-contained
package**: its typed declaration objects + frontend implementations co-live in one place.
Those declarations lower to core-owned, kind-keyed neutral extension envelopes; no
per-widget Python spec class needs to enter core or cross the canonical app boundary.

**The fix.** Structure built-in widgets the same way — **self-contained packages**, each
owning its typed authoring declarations + frontend implementations, discovered uniformly,
and lowering through neutral extension specs. Then:
- `core` = **pure kit**: kind-keyed extension specs, `AppSpec`/`Field`/bindings — the
  language-neutral vocabulary every widget builds on, with **no** per-widget specs.
- The typed authored specs (`LevelMarker` and morphology geometry)
  leave core or become package-local declaration values.
- This also removes the remaining special built-in source paths and discovery divergence:
  a widget-package co-locates its public authoring + self-registration.

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

**Validation snapshot (2026-08-06):** `poetry run python -m pytest -q` passes all 39 tests. The
findings below are architectural gaps not exposed by the golden alpha suite.

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

#### Additional rendering and discovery gaps

1. **2-D surgical refresh is planner-only, not end-to-end.**
   `register_view_refresh_schema("spectrogram_test", patch={"spec_axes": ...})` is
   covered by a test that asserts the planner emits `RefreshTarget("spec_axes", ...)`.
   The frontend dispatch loop, however, consumes only target kind `"extension"` for
   ordinary extension hosts, plus target kinds registered by the 3-D visual registry.
   A custom 2-D target is dropped; no partial-refresh host method is invoked. Section
   1A's optional surgical-refresh step must therefore be read as **not implemented for
   2-D yet**. Either implement a partial-target host contract or keep the schema private
   to paths that can actually dispatch it.

2. **Novel panel kinds validate but do not render.**
   Core validation correctly accepts a view whose `panel_kind` is an arbitrary new
   string, but VisPy panel creation recognizes only `view_3d`, `controls`, and
   `extension`; any other kind returns no widget. The existing test proves declaration
   and validation parity, not frontend parity. Either add a panel-host registry or stop
   describing novel panel kinds as fully first-class.

3. **Every registered 3-D visual is mounted in every 3-D panel.**
   `create_3d_visuals()` instantiates all global factories for each panel, even though an
   independent-canvas panel is constrained to exactly one primary view. Installing a
   plugin therefore adds allocation, side effects, and possible failures to unrelated
   panels. Instantiate the visual required by the panel's view kind (and any explicitly
   declared collaborators) instead of treating the global registry as a mount list.

4. **3-D refresh target names form an unsafe global namespace.**
   `_TARGET_TO_VISUAL[target_kind] = visual_kind` silently lets a later registration
   steal a target from an earlier visual. This is especially likely for generic names
   such as `operator_overlay`. Reject collisions or scope local target names by their
   owning visual kind; do not rely on import order.

5. **The registration family is neither cohesive nor uniformly public.**
   Only the ordinary renderer path is exported from `compneurovis.frontends.vispy` and
   entry-point-discovered. The 3-D visual, render-config, refresh-schema, and operator
   adapter registries require internal module imports. Some reject duplicate claims;
   others silently overwrite them. A third-party-facing registration contract needs one
   documented import surface, consistent collision behavior, and discovery before panel
   construction/refresh planning.

6. **The 3-D visual protocol understates its real contract.**
   `Viewport3DVisual` declares `clear()` and `pick_entity()`, while the frontend
   unconditionally invokes `refresh_for_target(...)` and optionally probes other hooks.
   Make the required method part of the protocol and describe optional capabilities in
   explicit protocols or one registration descriptor.

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

1. **Build PointCloudPlaneSlice + Scatter2D.** Use the public operator/output/contribution
   path, keep point-cloud slab selection topology-specific, and prove one control change
   refreshes the 3-D overlay plus ordinary 2-D scatter data.
2. **Finish renderer parity.** Installed 3-D discovery, collision checks, and relevant-only
   mounting have landed. Give 3-D the same resolved-properties contract as 2-D and either
   implement 2-D partial-target dispatch or remove the premature promise.
3. **Do widget-as-package after the seam is stable.** Otherwise the restructure merely moves
   current special cases into new directories and makes the eventual public API harder to
   change.
4. **Converge controls separately.** Ordinary control panels and extensible control kinds remain
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

1. **Pain #1 — public authoring** is the highest-value next step: promote geometry,
   selection, and operator declaration to public `context` methods (mirroring `data`/`grid`/
   `view`). This is Phase-4's unfinished authoring half and unblocks *interesting*
   third-party widgets. Prove it the Phase-4 way: *could `surface` have been authored through
   the public path?* — make the answer yes.
2. **Pains #2–#5 — the 3-D-symmetry cluster:** entry-point discovery for 3-D, a
   `properties`-based (not typed-config-assuming) 3-D refresh contract, folding the 3-D
   registrations into one call, unifying built-in discovery. Tidy, well-scoped.
3. **Widget-as-package (§2B)** is the large structural payoff that also retires the
   remaining core-resident authored specs. Sequence it after #1 (which defines the public
   authoring surface a package would use).

Hold the §3 guardrails throughout — especially the grep acceptance check (guardrail 2) and
no-junk-drawer (guardrail 4), which are the two most often violated mid-refactor.
