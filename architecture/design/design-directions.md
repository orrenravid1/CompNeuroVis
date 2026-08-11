---
title: Design Directions
summary: Consolidated, still-relevant architecture feedback and open directions, distilled from the refactor-era proposals and reviews.
---

# Design Directions

New active feature proposals may live in `design/proposals/`; completed proposals
are consolidated into durable architecture records. Files under `design/review/`
are historical audit inputs and must be explicitly marked superseded when their
findings have landed.

**Consolidated:** 2026-07-11

This is the durable distillation of the actor/`AppSpec` refactor-era record.
The detailed widget-authoring refactor is consolidated separately in
[Widget Authoring Architecture](widget-authoring-architecture.md). Historical
reviews are not current implementation guidance; `src/` and current examples
remain authoritative.

Everything below is a **direction, not a settled decision.** Status is marked
honestly against the current tree:

- ✅ **Done** — landed in code.
- 🟡 **Partial** — the mechanism exists but the full idea isn't realized.
- ⬜ **Open** — not started; still a real direction.

Source documents distilled here (all now removed): `architecture-parity-audit`,
`compneurovis-current-state` / `compneurovis-refactor-analysis` (2026-06-13),
`compneurovis-arch-evaluation` (+ the paired PDF), `backend-transport-frontend-refactor-log`,
`composable-authoring-proof`, `layout-workbench-proposal`, `panel-layout-updates`,
`websocket-transport-proposal`, `derived-data-monitors`, `timing-sampling-refresh-state`,
`canvas-backend-rendering-state`, and the personal refactor log.

---

## The through-line — one mutable handle model over the message protocol

The sections below are individually real, but they converge on one organizing
principle worth naming first, because it decides *how* the others get built. The
ambition is **matplotlib's ergonomics over the actor/message runtime**: a single
authoring surface where the simulator, the data's origin, and the transport seam all
drop out, and where every part of a live app — data, panels, controls, layout, which
panels even exist — is a handle you can set at any time. Two ideas carry it.

**1. Data is an origin-agnostic *sampleable*.** A panel should not know whether its
series is a NEURON `_ref_v` sampled per solver step, a jax array, a Python callable
over shared state, or a `Field` arriving from a remote fragment. All of those are one
thing: something that, given a tick, yields values (+ coords). Today this is *three*
sibling surfaces — `record_refs` (backend-sampled NEURON refs), `line(read=)` (a
per-frame callable), and `line(source=)` (an already-declared field) — that an author
must choose between, with different sampling cadences falling out silently (per-step
vs per-frame). Unifying them behind one `sample()` concept makes a panel genuinely
"sample and send a message," and drops the simulator out of the panel surface
entirely: `record_refs` / `read` / `source` become *adapters* to a sampleable, not
rival APIs. **Status: 🟡 Partial** — the message layer is already origin-invariant
(everything is `Field` deltas regardless of source); the *authoring* surface is not.

**2. Panels, controls, and layout are live handles.** `line(...)`, `slider(...)`,
`layout(...)` return objects whose every property — a plot's y-limits or title, a
control's options/range/default, the grid, the set of panels — is settable at any
time, and each set lowers to the patch protocol that already exists underneath
(`ValueChange` for values; `FieldReplace`/`FieldAppend` for data; the id-keyed spec
patches `ControlPatch` / `ViewPatch` / `OperatorPatch`; and `PanelPatch` /
`LayoutReplace` for placement — the last extended by §4). This is matplotlib's artist
model: hold the
thing, mutate it. It *subsumes* several separately-filed gaps — a control whose
`options` depend on another control's value (dependent controls), runtime relayout,
and "which panels exist" all become "a handle property was set," not distinct
features. The declarative `cnv.line(...)` / `cnv.layout(...)` calls are just the
*initial* state of these mutable handles. **Status: ⬜ Open** (the patch substrate is
partly built; the handle-level mutation surface is not). Groundwork already in code:
source-level widgets return typed `PanelRef` variants such as `LineRef`, `BarRef`,
and `Network2DRef`. These refs provide stable identity for future message-backed
mutation without pretending that mutation exists today.

### Two constraints that keep the runtime honest (it is not literally matplotlib)

- **Mutation is message-backed, not direct.** matplotlib mutates objects in one
  process; here a handle setter must emit a patch that crosses the bus — possibly a
  process or network seam — to whichever actor *owns* that state. So the handle API is
  a facade that feels synchronous but is eventually-consistent, and ordering is real
  (the class of the replace-past-append reorder the bus now guards against, §0).
  Design the setters as "emit a patch, the owner applies it," never "mutate a local
  object and hope it syncs." The layer this lowers to already has the right shape and
  must keep it: a **uniform, id-keyed, per-declaration patch family** —
  `ValueChange` (value) · `ControlPatch` / `ViewPatch` / `OperatorPatch` (spec, one
  peer per catalog kind, controls not privileged) · `PanelPatch` / `LayoutReplace`
  (placement/structure). **Anti-rot invariant:** handle setters lower onto these
  members; they must never resurrect a *bundled* or *kind-privileged* patch. The
  legacy `session/protocol.py` `ScenePatch` (value + spec + scene in one message) was
  exactly that; the refactor split it apart, and the handle model consumes the split
  pieces rather than re-bundling them for authoring convenience.
- **Samplers have a locus.** A NEURON `_ref_v` can only be sampled in the backend,
  per solver step; a callable over author-side state can be sampled anywhere. The
  surface can be uniform, but the runtime must *place* each sampleable on the right
  actor at a chosen cadence. matplotlib never faces this because everything is local.
  So: one authoring vocabulary, but a compiler decides where each sampler runs and how
  often (this is where the per-field `sample_dt` work of §5 belongs).

### Two design cautions

- **Aim for the Artist/Axes mutability, not pyplot's global state.** The good part of
  matplotlib is "hold a handle, set anything on it." The bad part is the implicit
  global *current figure*. CompNeuroVis already has a whiff of that (`cnv.show()`
  plus the module-level registered-current-source, §7's ambient authoring app); going
  "matplotlib" should push us *more* handle-first, not toward a global stateful facade
  — otherwise "settable whenever" rots into "settable from wherever, by whom?" and the
  ownership story is lost.
- **Structural dynamism widens the frontend protocol.** "Values change on a fixed app"
  is cheap to serialize and trivial for a non-Python client to implement; "add/remove
  panels and relayout at runtime" makes every structural op a wire message a
  Unity/browser frontend must also implement (§3; Part D of the authoring proposal).
  The matplotlib ergonomics are worth it, but they enlarge the contract a swappable
  frontend has to honor — so *how far* structure is dynamic should be decided **before**
  the wire protocol is frozen, not after.

### How the numbered directions serve this

This through-line is not a competing item; the sections below are its pieces. §1
records the open kind/host mechanism that has landed. §2
(selection-as-a-value) is the same "everything is a value/binding" idea generalized —
a selection is just another settable value in the namespace. §3 (serializable
protocol) is what the handle mutations serialize *to* across a seam. §4 (layout as a
split-tree + `PanelPatch` / `LayoutReplace`) is layout becoming a settable property.
§5 (sampling cadence, per-field `sample_dt`) is the sampler-locus constraint made
concrete. §6 (`Feature` bundles) is what you build *out of* these handles. Read that
way, the [Widget Authoring Architecture](widget-authoring-architecture.md) records
the implemented authoring seam, its guardrails, and the adjacent work that remains.

---

## 0. What already landed (don't relitigate)

The spine the refactor set out to build is real and in code, so these are closed:

- **One declarative target.** Everything compiles to a single immutable `AppSpec`
  built from four catalogs (data, view, interaction, layout). The inline layer
  lowers into the *same* `AppSpec` as a real backend — "inline is only sugar over
  the core" holds in code, not just intent. ✅
- **Backend/frontend symmetry.** Both are `ActorBase` peers with identical
  emit/handle/tick. The `Bus` is not an actor and never infers direction from
  role. ✅
- **Generic strict routing.** `RunSpec`/`RoutingSpec` express arbitrary
  topologies; unroutable messages raise rather than broadcast. ✅
- **Declaration/projection split.** `AppSpec`/`FieldSpec` are immutable
  declarations; `AppProjection`/`Field` are the actor-local mutable read model. ✅
- **Immutable specs.** Frozen dataclasses + read-only arrays + `FrozenDict`. ✅
- **The authoring-tier thesis, mostly.** The old external evaluation's core
  recommendation — *keep the core IR, stop making authors program against it
  directly, add a convenience tier* — is largely realized by the inline layer
  (`cnv.source().morphology/line/bar/control/action`, `cnv.layout`, `cnv.show`).
  See §6 for the part that remains. 🟡
- **ctx-first callbacks.** The old "zero-arg inline actions" mismatch is gone;
  setters/actions/handlers now take a `ctx`. ✅
- **`derive` + `bar`/`state_graph`/`surface`.** The derived-data-monitors proposal
  landed: `derive(over=, window=, target="field"|"state")` with sampling split
  from throttled evaluation, `bar` as a view kind, and `on_control` + `ctx.controls()`
  for recording. ✅
- **Producer-side field coalescing.** The bus keeps only the latest `FieldReplace`
  per field and merges compatible `FieldAppend`s within a pump cycle (while
  preserving replace→append ordering so shape-changing replaces are never
  reordered past their appends). ✅
- **Source-layer de-duplication.** The neuron/jaxley ~80% copy-paste flagged by
  the parity audit (M4) is largely collapsed into a shared `SourceBackendMixin`
  and shared record/history plumbing. 🟡

---

## 1. Open widget and host registries — landed

The genericity gap is closed for the supported desktop/source path. Canonical
`ViewSpec`, `GeometrySpec`, and `OperatorSpec` values are kind-keyed data
envelopes. Vispy renderer, scene-layer, operator, contribution, control/action,
and panel-host behavior is registered frontend-locally. Built-ins and third
parties use the same calls, and adjacent scripts do not require separate
packaging. The complete contracts and remaining limitations live in
[Widget Authoring Architecture](widget-authoring-architecture.md).

**Status: ✅ Done.** Do not reintroduce core widget subclasses, hard-coded panel
kind dispatch, or a separate third-party canonical path.

---

## 2. Selection-as-a-value; declarative cross-panel linking

**Direction:** treat a selection (a clicked entity, a brush extent, a hovered
series) as a *named value in the binding namespace*, not an event handler. Views
bind fields/selectors to that key; linking two panels becomes "they bind the same
key," not plumbing. This also gives action payloads somewhere to land — actions
and selections *produce values into the namespace* rather than being side effects.

The substrate is here: `ValueBindingSpec(key)` (in `core/values.py`) references a
namespace value, `ValueChange` carries keyed updates through `ValueBindings` on
every actor, and morphology exposes a `SelectionRef` plus a selection-filtered
`DataRef` that `line(source=morph.selection)` consumes. Multiple morphology
widgets now keep independent exact selection keys, including multiple selections
over the same geometry. What's not yet general is arbitrary brush/hover selection
shapes and author-directed multi-view linking through one deliberately shared key.
**Status: 🟡 Partial** (entity selection and selection-driven data work; general
cross-widget selection linking remains open).

---

## 3. Serializable protocol + network transport + composition

Three facets of one body of work, in dependency order.

- **Serializable wire protocol.** `AppSpecDeclared` currently ships the live
  `AppSpec` object and field deltas carry raw NumPy arrays, so nothing crosses a
  process/machine boundary as a stable format. Needed: a serializable spec
  envelope + a typed binary convention for array payloads (dtype + shape + raw
  bytes). This is the prerequisite for everything else here. **⬜ Open.**
- **WebSocket transport.** Concrete plan exists (from the websocket proposal): a
  `WebSocketTransport` presenting the same `Transport` protocol as the pipe
  transport and integrating with the Qt loop, plus a Qt-free `run_backend_server()`.
  Immediate driver: run a Linux-native backend in WSL while VisPy renders on the
  Windows host (pipes can't bridge that). Codec: **pickle-first behind a two-function
  swappable seam** (trusted loopback, same interpreter), swap to msgpack+numpy when
  a non-Python client (Unity/browser) appears. Keep transport and frontend as
  independent axes; the language-agnostic wire protocol is what makes a future
  non-Python frontend possible without a serialization redesign. Open sub-questions:
  reconnection (raw `websockets` vs Socket.IO), a `startup_scene`/loading-state
  hook, default port. **⬜ Open.**
- **Composition / remote lowering.** More nuanced than a flat stub. `cnv.show()`
  with multiple *independent* sources already launches them via `launch_sources`.
  What is deliberately stubbed: `ComposedSource._make_backend` and
  `RemoteSource._make_backend` raise `NotImplementedError` (the `cnv.compose(...)` /
  `cnv.remote(...)` paths), and `cnv.layout(...)` *across* multiple sources raises
  ("the integrated app-spec compiler must place the grid"). So the honest state is:
  multi-source launch works; unified composition/layout and remote lowering are the
  open pieces, and they depend on the serializable protocol above. **🟡 Partial.**

---

## 4. Layout: grid → recursive split-tree workbench

**Direction:** eventually replace the transitional flat `panel_grid` (rows of cells; today's
`cnv.layout(((a, b), (c,)))`) with an explicit recursive **split tree** — nested
horizontal/vertical `SplitSpec` nodes placing panel ids, with per-child sizing
rules (`fraction` | `auto` + `min_size`), frontend-owned drag state, and authored
default layout kept separate from saved user layouts. Adopt the Unity/Unreal
recursive-splitter shape, not Blender's full screen graph. Camera and other
renderer-specific properties already belong to views rather than `PanelSpec`;
preserve that separation.

The narrow runtime messages already exist: `PanelPatch` updates one panel and
`LayoutReplace` replaces placement while preserving projected data. The open work
is the recursive authored layout model and polished source-level mutation API,
not inventing another patch family. **Status: 🟡 Partial.**

---

## 5. Timing, sampling, and rendering performance

The app-wide scheduling direction is now specified in the
[Adaptive Presentation Scheduler proposal](proposals/adaptive-presentation-scheduler.md).
That proposal supersedes fixed per-widget refresh rates as the target architecture;
the items below remain concrete optimization inputs and supporting work.

The multi-clock model is the right architecture and should be preserved: solver
`dt`, sampling cadence, emission/display cadence, transport cadence, per-view
`max_refresh_hz`, and UI-loop cadence are **separate clocks that stay decoupled**
(changing batching must not change solver accuracy; slow rendering must not block
controls). Field semantics: latest-state fields → `FieldReplace` (coalesceable);
historical fields → `FieldAppend` with bounded retention; on-demand history (only
selected rows sampled) is the right interactive default, full entity-by-time
history a capability, not the default shape.

Remaining performance work, roughly in order of leverage:

- **Per-field / per-line `sample_dt`** — sample slower than the solver step
  without losing solver accuracy. 🟡 Already implemented on neuron
  `record_refs(sample_dt=)` (with interval logic in the source); the open part is
  generalizing it to other providers and to `line`/`morphology` fields.
- **Priority command lane** — clicks/keys/control changes shouldn't queue behind
  large field updates; a command-first drain policy. ⬜
- **Frontend ring buffers** for rolling-window line fields to cut append/copy
  allocation. ⬜
- **Visibility-aware refresh** — hidden/collapsed/tiny panels keep state current
  but skip expensive redraw (matters more once layout is dynamic, §4). ⬜
- **Spatial latest-state fast paths** — when geometry/style are unchanged, update
  only the scalar/color payload, not a mesh rebuild. ⬜
- **Line-plot draw reduction** — visible-pixel downsampling, incremental curve
  append when axes/window are stable. ⬜
- **Producer-side coalescing** — largely done at the bus (§0); the remaining
  piece is bounding visual queue growth when the frontend falls behind. 🟡

Canvas/rendering investigation (do **not** redesign dataflow around it): the near-
term posture is to keep the current model and instrument. Worth doing when there's
time: realized `QOpenGLContext` swap-interval logging, a tiny-scene baseline in the
same embedded canvas, a `QOpenGLWindow` container spike (keeps the app in Qt while
avoiding the current widget-canvas path), render-scheduling groups (≤1 heavy spatial
draw per UI turn), and — separately from the interactive path — a **headless/export
render path** (EGL/OSMesa) for noninteractive snapshots/figures. Open: whether the
Windows driver/DWM path will ever honor a disabled swap interval; how much of the
measured 31–47 ms draw is swap/composition vs scene traversal. ⬜

---

## 6. Authoring tier — the remaining thesis

The external evaluation's three-tier pattern (stable core IR · convenience
authoring tier · execution-only runtime) is the frame the refactor followed, and
most of it landed (§0). The parts still worth pursuing:

- **`Feature` as a reusable authored bundle.** A feature contributes state,
  controls, traces, tools, and maybe views declaratively, without touching the
  renderer or transport — the analog of a Unity prefab / Unreal plugin / Blender
  add-on. Domain packages could then ship `MorphologyFeature`, `SpikeRasterFeature`,
  etc. Today authoring is per-source method calls, not composable feature bundles.
  ⬜
- **Tools as transient operators.** Model interaction (pick, brush, orbit, scrub)
  as ephemeral, event-driven operators over stable scene/state — Blender's
  operator/mode split — rather than imperative handlers or persistent scene
  objects. 🟡 (interaction is `ctx`-based now, but not a first-class Tool/operator
  model).
- **Reproducible authored specs.** Longer term, treat an authored `AppSpec` the
  way ParaView treats state files / Python traces — a high-level reproducible
  artifact over a stable pipeline core.

The load-bearing external analogies to keep in mind: **Arbor** (`recipe` vs
`simulation` + a `single_cell_model` convenience) and **OpenMM** (`System`/`Force`
vs `Context`/`Platform` + an application layer + XML serialization) are the closest
description/execution splits; **LFPy-over-NEURON** is the cautionary tale about
forcing authors to live at the raw layer; **Panel/Param** and **Jupyter traitlets**
are the models for declarative control bindings over typed state.

---

## 7. Hardening / boundary-smell checklist

Small, mostly-independent items flagged across the audits. Several are already
closed by the refactor; the open ones are cheap and worth a sweep:

- **Stray presentation timing output.** Keep hot-path diagnostics structured and
  opt-in; do not add unconditional console output. ⬜
- **Ambient authoring app.** `InlineApp` now has a coherent owner in
  `inline/app.py`, separate from the module-level facade in
  `inline/authoring.py`. Normal `cnv.source()` / `cnv.layout()` / `cnv.show()`
  still use one ambient app, and an explicit root `App()` escape hatch is not
  public. ⬜ (partially resolved: ownership split complete; explicit authoring
  remains open)
- **`ValueOrBinding = Any`** weakens typing on view fields (`core/views.py:9`). ⬜
  (confirmed)
- **`RenderedFrame` shares the update stream.** It's an `UpdatePayload`
  (`core/messages.py:120`); conceptually it's what a headless render-target actor
  *emits* — a separate output stream. ⬜ (confirmed)
- **Notebook promotion.** The environment-driven render-process/RFB fork and
  widget-specific morphology/trace actors are gone. Notebook RunSpec construction
  is frontend-local and explicit; one generic renderer process reuses registered
  Vispy panel lifecycles while the kernel shell owns open ipywidget control/action
  registries. Remaining work is camera/picking interaction, layout parity, and
  release hardening. 🟡

Resolved since the audits (verified — dropped from the open list): notebook actor
placement is declared and independent of widget kinds or environment flags; the hardcoded
`scratch/perf_stats.txt` perf-log block is gone from `src/`; `RunSpec.routing` is
**not** a dead field — `run.py` reads it (`run_spec.transport(actors, run_spec.routing)`).

---

## 8. Suggested ordering

If/when this work is picked up, the audits converged on roughly this leverage
order:

1. **Selection-as-a-binding-value** (§2) — declarative cross-panel linking; shares
   its mechanism with the serialization work.
2. **Serializable protocol** (§3) — the gate for any network transport.
3. **WebSocket transport + composition lowering** (§3) — once the protocol
   serializes.
4. **Layout workbench** (§4) — grid→tree over the existing generic panel model.
5. **Performance sweep** (§5) and **hardening** (§7) — incremental, independent.
