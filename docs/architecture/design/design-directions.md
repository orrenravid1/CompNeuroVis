---
title: Design Directions
summary: Consolidated, still-relevant architecture feedback and open directions, distilled from the refactor-era proposals and reviews.
---

# Design Directions

**Consolidated:** 2026-07-11

This is the single surviving distillation of the refactor-era design record. It
replaces the `design/proposals/` folder and the `design/review/` folder, which
were a stack of dated snapshots, refactor logs, audits, and outside evaluations
produced *during* the actor/`AppSpec` refactor. Those documents did their job —
the refactor landed — and most of their findings are now either implemented or
superseded. The durable, still-forward-looking substance is captured here; the
originals remain in git history if a specific detail is ever needed.

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

## 1. The genericity gap — open panel/view registry

**The single most-cited open direction.** The base spec is meant to host apps
well beyond plotting (a NeuroML-style editor, a model-comparison grid, a
teacher/student split, a robotics-plus-simulator view). Today it cannot, because
the vocabulary is closed: `PanelSpec.kind` is validated against a hardcoded set
(`view_3d`, `line_plot`, `controls`, `state_graph`, `bar_plot`) and `ViewSpec`
subtypes are a fixed plotting-oriented set that `app_spec.py` imports concretely
to type-check panels.

**Direction:** replace the enum + `isinstance` checks with an open
`kind → (validator, render capability)` **registry**, so a new panel/view kind is
*registered* rather than a core edit. This is the change most aligned with the
generic-base ambition; it's the same open-contract pattern that lets Unity
packages / Unreal plugins extend a stable runtime. When `bar` was added it was a
deliberate "minimal enum bump" with the registry explicitly deferred — that debt
is now several kinds deep (bar; a poster-era raster / space-time heatmap was
also wanted). **Status: ⬜ Open.**

---

## 2. Selection-as-a-value; declarative cross-panel linking

**Direction:** treat a selection (a clicked entity, a brush extent, a hovered
series) as a *named value in the binding namespace*, not an event handler. Views
bind fields/selectors to that key; linking two panels becomes "they bind the same
key," not plumbing. This also gives action payloads somewhere to land — actions
and selections *produce values into the namespace* rather than being side effects.

The substrate is here: `ValueBindingSpec(key)` (in `core/values.py`) references a
namespace value, `ValueChange` carries keyed updates through `ValueBindings` on
every actor, and morphology already exposes `morph.selection` as a `FieldSource`
that a `line(source=...)` consumes. What's not yet general is arbitrary selection
values (brush/hover extents) as first-class binding keys with multi-view fan-out.
**Status: 🟡 Partial** (single selection→trace works; general selection-as-value
linking is open).

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

**Direction:** replace the transitional flat `panel_grid` (rows of cells; today's
`cnv.layout(((a, b), (c,)))`) with an explicit recursive **split tree** — nested
horizontal/vertical `SplitSpec` nodes placing panel ids, with per-child sizing
rules (`fraction` | `auto` + `min_size`), frontend-owned drag state, and authored
default layout kept separate from saved user layouts. Adopt the Unity/Unreal
recursive-splitter shape, not Blender's full screen graph (right upper bound, too
much machinery for now). This also absorbs the **`PanelSpec` field-bloat smell**:
camera fields (`camera_distance/elevation/azimuth`) that most panel kinds never
use become part of kind-specific panel specs (`View3DPanelSpec`, `LinePlotPanelSpec`,
`ControlsPanelSpec`) instead of first-class fields on every panel.

Companion runtime capability (from panel-layout-updates): narrow updates for
panel changes without a full scene rebuild — `PanelPatch` (swap one panel's
control/view/action ids or title in place; primary use case is model-variant
control-set switching) and `LayoutReplace` (swap the whole arrangement, preserving
fields/render state). Reconcile by stable `panel_id`. **Status: ⬜ Open.**

---

## 5. Timing, sampling, and rendering performance

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

- **Two stray `print()`s in hot paths** — `backends/neuron/geometry.py:86`
  ("Meta file generated…") and `frontends/vispy/renderers/morphology.py:72`
  ("Morphology visual generated…"). Route through `core/_perf`/diagnostics. ⬜
  (both still print — confirmed)
- **Session singleton.** The inline session is a module-level singleton
  (`inline/__init__._app = InlineApp()`); an explicit `App()` escape hatch isn't
  public. ⬜ (confirmed)
- **`ValueOrBinding = Any`** weakens typing on view fields (`core/views.py:9`). ⬜
  (confirmed)
- **`RenderedFrame` shares the update stream.** It's an `UpdatePayload`
  (`core/messages.py:120`); conceptually it's what a headless render-target actor
  *emits* — a separate output stream. ⬜ (confirmed)
- **Notebook render-process as declared topology.** `CNV_NOTEBOOK_RENDER_PROCESS`
  (+ `CNV_NOTEBOOK_RFB`) still drive a multi-way `use_render_process` /
  `use_morphology_process` / `use_trace_process` fork across `_source_runtime.py`,
  rather than a first-class declared multi-actor topology with a generic
  frame/camera contract and an explicit frame-stream policy
  (rate/quality/backpressure/coalescing). The `rfb_widget` path exists; making the
  decomposition *declared* rather than branch-synthesized is the open part. 🟡
  (confirmed)

Resolved since the audits (verified — dropped from the open list): the hardcoded
`scratch/perf_stats.txt` perf-log block is gone from `src/`; `RunSpec.routing` is
**not** a dead field — `run.py` reads it (`run_spec.transport(actors, run_spec.routing)`).

---

## 8. Suggested ordering

If/when this work is picked up, the audits converged on roughly this leverage
order:

1. **Open the panel/view kind registry** (§1) — unblocks the non-plotting app
   types that motivated the generic base.
2. **Selection-as-a-binding-value** (§2) — declarative cross-panel linking; shares
   its mechanism with the serialization work.
3. **Serializable protocol** (§3) — the gate for any network transport.
4. **WebSocket transport + composition lowering** (§3) — once the protocol
   serializes.
5. **Layout workbench** (§4) — grid→tree, absorbs the `PanelSpec` camera bloat.
6. **Performance sweep** (§5) and **hardening** (§7) — incremental, independent.
