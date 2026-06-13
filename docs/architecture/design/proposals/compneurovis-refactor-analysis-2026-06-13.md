# CompNeuroVis Alpha Refactor — Architecture Analysis & Cross-Pollination Notes

**Date:** 2026-06-13
**Branch reviewed:** `user/orren/compneurovis-alpha-refactor`
**Scope:** `src/compneurovis` (the reliable tree), the design proposals under `docs/architecture/design/proposals/`, and a set of insights drawn from an outside design study.

---

## 1. What this document is

This is a status read of where the alpha refactor stands against its own stated goals, followed by a set of design insights imported from an unrelated thought experiment (described in §9). It assumes no prior familiarity with that thought experiment. The intent is to (a) record what has actually landed in code versus what is still scaffolding, and (b) capture a small number of transferable ideas while being explicit about which ones do *not* transfer and why.

This is an internal modeling-UI tool for academic computational-modeling workflows. Nothing here involves biology, wet-lab work, or security; "neuron," "morphology," and similar terms refer only to data shapes and visualization panels.

---

## 2. The target architecture (goals, restated)

The refactor is pursuing two surfaces that pull in opposite directions on purpose:

- **A maximally composable base.** Everything compiles down to one declarative `AppSpec`. On top of that, a runtime topology (`RunSpec`) of *actors* — backend simulators and frontends — can be wired in arbitrary fan-in/fan-out arrangements, locally or across processes/machines, with as many backends and frontends as a workload needs.
- **A maximally convenient inline layer.** A thin authoring API (`cnv.source(...).trace/control/action`, `cnv.show()`) for the common matplotlib-style case, hiding nearly all of the low-level machinery.

A stated stretch goal: the base `AppSpec` should be generic enough to host apps well beyond standard plotting workflows — e.g. a physics-plus-simulator robotics view, a NeuroML-style editor, a model-comparison framework, or an educational tool with separate student and teacher views. The base must support *any* topology; the inline layer must hide *all* of it.

---

## 3. Executive summary

The spine the refactor set out to build is real and largely in place. Everything genuinely converges on one `AppSpec`; backend and frontend are now the same kind of peer; and routing is generic and role-agnostic. Most of the high-priority concerns from the prior internal review (the 2026-05-24 feedback) have been addressed in code, several of them more strictly than recommended.

The largest remaining gap is the inverse of what that review worried about. The low-level spec is now clean and well-guarded, but it is **not yet generic enough to host the non-plotting apps named as stretch goals.** The panel and view vocabulary is a closed, hardcoded set validated inside the core. Closing that gap is the single change most aligned with the project's own ambitions, and §9 describes an external pattern that models the fix concretely.

The networked-topology story is *expressible* but not yet *runnable across machines*: the topology model exists, but only in-process and pipe transports are implemented, and the message protocol still carries live Python objects, so nothing serializes across a real network boundary yet. Multi-source inline composition is deliberately stubbed rather than faked, which is the right call.

---

## 4. What has landed (the spine)

**One declarative target.** `AppSpec` is now built from four catalogs — `DataCatalog` (fields, geometries), `ViewCatalog` (views, operators), `InteractionCatalog` (controls, actions), and `LayoutCatalog` (layouts, panels). The older flat constructor forms are gone, and the legacy builder path is quarantined under `deprecated/`. The inline layer lowers into this exact same `AppSpec` (`_build_inline_app_spec`, `append_bindings_to_app_spec`), and a real simulator backend lowers via `build_startup_app_spec()`. The "inline is only sugar over the core" claim therefore holds in code, not merely in intent.

**Backend/frontend symmetry.** Both are `ActorBase` peers with identical emit/handle/tick surfaces. The `Bus` is explicitly *not* an actor — it never appears in the user's actor hierarchy and is never type-checked against. Message direction is never inferred from an actor's "role"; any actor may emit any message.

**Generic, strict routing.** `RunSpec` + `ActorSpec` + `RoutingSpec` express arbitrary topologies. The `Bus` routes by (1) an explicit `RoutedMessage` envelope, then (2) the first matching ordered `RouteSpec` rule (matching on intent, registered message-type name, and optional payload attributes). There is no implicit broadcast fallback: an unroutable message raises `BusRoutingError`. The launch path is cleanly factored — `run_orchestrator` opens the fabric and spawns nothing; `start_app` is `run_orchestrator` plus per-actor spawn; `run_actor` connects one actor to one channel — so local and remote launches share one code path.

**Declaration/projection split.** `AppSpec` (and its sub-specs) are immutable startup declarations. `AppProjection` is the actor-local, mutable read model derived from the spec plus runtime updates: it holds materialized `Field` values, live metadata, and the current active-layout selection, while the declared `AppSpec` stays untouched. The `FieldSpec` (declaration) vs `Field` (live value view) distinction is implemented and enforced.

---

## 5. Status of the prior feedback items

The 2026-05-24 review raised twelve items. Their current state in code:

| # | Item | Status | Notes |
|---|------|--------|-------|
| 1 | Make specs genuinely immutable | **Done** | `readonly_array` + `setflags(write=False)` for arrays; `FrozenDict` for mappings. Porous immutability closed. |
| 2 | Clarify AppSpec normalization | **Done** | `validate_app_spec` now validates without mutating; layout/grid normalization moved out to the authoring layer (`build_default_layout`). `AppSpec` rejects panels lacking an explicit grid. |
| 3 | Stricter bus fallback routing | **Done (stricter)** | No fallback at all; unroutable messages raise `BusRoutingError` rather than broadcasting. |
| 4 | Decide transport serializability | **Open** | `AppSpecDeclared` ships the live `AppSpec` object; `FieldAppend`/`FieldReplace` carry raw NumPy arrays. Still a local-Python protocol. |
| 5 | Fix inline action payload semantics | **Open** | `InvokeAction` carries a `payload` dict, but inline `ActionBinding.fn` is still invoked as a zero-arg `fn()`. The declared/runtime mismatch the review flagged remains. |
| 6 | Keep catalog-based AppSpec canonical | **Done** | Only the catalog form exists. |
| 7 | Validate routing rules | **Open** | `MessageMatch.attrs` is still unchecked against registered payload types. |
| 8 | Treat `cnv.show()` as session sugar | **Partial** | `InlineApp` accumulator and `_reset_inline_session()` exist, but the module-level singleton plus bare `source()`/`show()` is still the only public surface; the explicit `cnv.inline.App()` escape hatch is not exposed. |
| 9 | Don't make composition look stable prematurely | **Done (stubbed)** | `ComposedSource` / `RemoteSource` / `RemoteActorRef` raise `NotImplementedError` rather than hiding composition inside one backend. Matches the review's own recommendation. |
| 10 | Separate sim/sample/flush/render clocks | **Open** | `InlineBackend` is still a fixed ~60 Hz `_FRAME_MS` loop; the clocks remain conflated. |
| 11 | `ValueOrBinding = Any` weakens typing | **Open** | Still `Any` in `views.py`. |
| 12 | `RenderedFrame` may belong to a separate stream | **Open** | Still a regular `UpdatePayload` in the same stream as model updates. |

From the 2026-05-25 personal log: the `PanelSpec` field-bloat smell is still present (it carries `camera_distance/elevation/azimuth` as first-class fields that most panel kinds never use), and the grid→tree layout move (the "layout workbench" proposal) is not yet done. Layout *resolution* is partially clarified — the authoring layer builds the grid and `AppProjection` owns the active-layout selection — but the recursive split-tree model is still a proposal.

---

## 6. The genericity gap (the key open issue)

The stretch goal is that the base spec can host arbitrary apps. Today it cannot, because the vocabulary is closed:

- `PanelSpec.kind` is validated against a hardcoded set — `view_3d`, `line_plot`, `controls`, `state_graph` — and `_validate_panel` raises on anything outside it.
- The `ViewSpec` subtypes are a fixed plotting-oriented set (`MorphologyViewSpec`, `SurfaceViewSpec`, `LinePlotViewSpec`, `StateGraphViewSpec`), and `app_spec.py` imports them concretely to type-check panels.
- `PanelSpec` carries 3D-camera fields as first-class attributes — the same "fields most panels don't use" smell noted in the personal log.

A NeuroML-style text editor panel, a model-comparison grid, or a teacher/student split simply has no representable panel or view kind today, and adding one means editing core validation. To meet the generic-base goal, the panel/view kind system likely needs to become an **open registry** — `kind → (validator, render capability)` — rather than an enum baked into `core/app_spec.py`. That single change is what would let the base layer host "apps of any sort" while the inline layer stays narrow and convenient. §9.2 describes an external system that demonstrates exactly this open-contract pattern.

---

## 7. Networking and multi-source reality

The topology *model* is present; the *wires* are not.

- `transports/` contains only `inprocess` and `pipe`. There is no network transport yet — a WebSocket transport exists only as a proposal.
- The message protocol carries live Python objects and raw NumPy arrays, so nothing serializes cleanly across a process or machine boundary (this is the same fact as feedback item #4).
- `cnv.show()` raises `NotImplementedError` for more than one source, and `ComposedSource`/`RemoteSource` lowering is stubbed.

So "one or many backends and frontends, wherever you like" is faithfully expressible in `RunSpec` but not yet demonstrable across machines. The honest framing: the abstraction is built and the transport/serialization layer beneath it is not.

---

## 8. Inline layer reality

The inline layer is in good shape for the single-source case. A `source` (callable, iterator, or simulator) owns its own `trace`, `control`, and `action` bindings; `cnv.show()` lowers a single source through the same `RunSpec`/`start_app` path as everything else; and `cnv.show(build)` runs a heavier simulation in a child process while rendering in-kernel, so a slow sim cannot starve the render loop. The two caveats above (the session singleton, item #8; and zero-arg actions, item #5) are the main rough edges, plus the fixed-rate loop (item #10).

---

## 9. Insights from an external design study

### 9.1 What the study is

As an outside reference, a fictional, never-built plotting library — referred to here as **the study** — was sketched in detail. It is *not* a dependency, a real package, or something to adopt wholesale; it is a thought experiment whose only value here is the design pressure it reveals.

The premise of the study is "interaction-first" plotting: instead of treating a chart as a one-shot rasterization with interactivity bolted on (the classic batch-renderer model), it treats *interaction* as the core abstraction and static export as the degenerate case (a frame with no events). It rests on three commitments worth naming because they map onto this project:

1. **A retained, reactive scene graph.** Plot elements are persistent nodes with state and dirty flags; changing data invalidates the minimal set of nodes and only those re-render.
2. **Dataflow instead of callbacks.** Data, widget values, and selections are *values that things subscribe to*; updates propagate through a dependency graph automatically, rather than through hand-written event handlers.
3. **Interaction as composable objects.** A brush, a hover probe, or a selection is an object that produces a *selection value*; any number of views can consume that value. Linking two views is therefore composition, not plumbing.

It also proposes a layered API (familiar one-liners on top, a grammar layer in the middle, the raw scene graph at the bottom, each layer implemented strictly in terms of the one below), and a wire protocol of "initial spec + columnar data buffers + small deltas afterward," with selections flowing back in the same delta shape.

### 9.2 What transfers, mapped to this repo

**Selection-as-a-value answers the action-payload problem (feedback #5).** The study's central move is that a selection is not an event handler but a named value many views subscribe to. This project already has the entire substrate, half-wired: `StateBindingSpec(key)` references a value in the binding namespace; `BindingValuePatch` is described in the protocol as "patch values in the runtime binding namespace… projection inputs, not canonical state"; and `ValueOrBinding = Any` lets a view field point at one. The synthesis: a selection (brush extent, clicked entity, hovered series) is a key in that namespace; a `LinePlotViewSpec.selectors` or `color_limits` binds to it; cross-panel linking becomes "two views bind the same key." That also gives `InvokeAction.payload` somewhere to land — actions and selections *produce values into the namespace* rather than being zero-arg side effects.

**The study's extensible "marks" are a working model of the genericity gap (§6).** In the study, chart marks and interactions are defined against a narrow node contract and *registered*, and a custom low-level node can be dropped into a high-level figure. That is precisely the open-registry pattern the closed `PanelSpec.kind` enum is blocking. The transferable lesson is structural, not cosmetic: a generic base and a familiar convenience layer coexist *because* the base contract is open and the top layer is a thin set of presets over it — which is this project's inline-vs-`AppSpec` thesis stated from the other direction. Replacing the kind enum and `isinstance` checks with a `kind → (validator, render capability)` registry would make a NeuroML editor panel or a teacher/student view a registered kind rather than a core edit.

**The wire protocol is a concrete template for feedback #4.** The study ships a serializable spec, then typed columnar buffers, then deltas, with selections flowing back in the same shape. This project's `FieldAppend`/`FieldReplace` already *are* the deltas; what is missing is exactly the two things the study separates — a serializable spec envelope (today `AppSpecDeclared` ships the live object) and a typed binary convention for NumPy payloads instead of pickling them. The "selections flow back the same way" point means the selection-as-value idea (above) and the serialization fix are the same work approached from two ends, and the symmetric bus already permits the upstream direction.

**Layer separation names something already being discovered here.** The study separates a bulk data layer that changes rarely from a cheap overlay layer that changes on every mouse move. That is the same split as `GeometrySpec` (structure) / `Field` + `FieldReplace` (values) / a selection overlay. The backlog note about updating per-node `face_color` in place without rebuilding adjacency is this project rediscovering the principle by hand. Making it explicit yields a **two-tier interaction model** suited to a distributed setup: cosmetic feedback (crosshair, hover) stays frontend-local and instant, while a selection that drives a backend filter travels through the bus. As a smaller corollary, the study's "same scene graph replayed to a different render target for export" is the clean conceptual home for `RenderedFrame` (feedback #12): it is what a headless render-target actor *emits* — a separate output stream — not an `AppProjection` update.

**A future fit, not a priority.** The study makes the visible data domain (the x-range after a zoom) itself a value that the data engine subscribes to, so server-side reduction (downsampling, density tiles) is demand-driven by the current view. This project's backlog already lists viewport-aware decimation; framed the study's way, the frontend's view domain becomes a binding value that propagates upstream to a backend, which reduces before emitting `FieldAppend`. It is expressible in the current architecture and worth noting, but it is later work.

### 9.3 What does *not* transfer (the instructive part)

The study's spine is a **synchronous, glitch-free, single-runtime reactive graph**, and on its interaction hot path nothing round-trips to the host language. That works only because it assumes one authoritative runtime that owns all state. This project's entire bet is the opposite: asynchronous message-passing between actors that may live in different processes or on different machines, with no single owner of state. A synchronous signal graph does not cross that boundary.

The practical consequence: adopt the study's *dataflow semantics* (a selection is a value; subscribers react) but realize them over the existing patch/projection mechanism — a "signal change" is a `BindingValuePatch` propagating through the bus, eventually consistent across actors, not a synchronous recompute. Importing an in-process signals runtime as the core would quietly contradict the distributed-topology goal. The places where this project is genuinely hard — multi-backend, multi-frontend, cross-machine consistency — are exactly the places the study gets to assume away. That boundary is where the analogy ends.

---

## 10. Suggested priorities

In rough order of leverage against the project's own goals:

1. **Open the panel/view kind system into a registry** (§6). This is the change most aligned with the generic-base ambition and unblocks the non-plotting app types named as stretch goals.
2. **Define selection-as-a-binding-value** (§9.2). It resolves feedback #5 cleanly, makes cross-panel linking declarative, and shares its mechanism with the serialization fix.
3. **Make the protocol serializable** (feedback #4): a serializable spec envelope plus a typed binary convention for array payloads. This is the prerequisite for any real network transport, and therefore for the multi-machine topology story.
4. **Land a network transport and composition lowering** once #3 exists, turning the currently-stubbed `ComposedSource`/`RemoteSource` into real multi-actor `RunSpec` wiring.
5. **Tidy the remaining boundary smells**: zero-arg actions (#5, folded into #2), the session singleton (#8), the conflated clocks (#10), `ValueOrBinding = Any` (#11), `RenderedFrame` as a separate output stream (#12), and the `PanelSpec` camera-field bloat.

The throughline: the refactor's abstractions are pointed the right way, and most of the work now is hardening the places where alpha conveniences could otherwise harden into platform contracts — and, distinctively, opening the base vocabulary far enough to match the ambition that motivated the refactor in the first place.
