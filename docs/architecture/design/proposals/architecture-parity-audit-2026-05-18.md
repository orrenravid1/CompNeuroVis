---
title: Architecture Parity Audit
date: 2026-05-18
status: review snapshot
scope: src/compneurovis/ only (docs, tests, examples/, skills excluded per request)
method: 5-agent code swarm vs. the vision in backend-transport-frontend-refactor-log.md + app_configuration_matrix.md
---

# Architecture Parity Audit — 2026-05-18

How well does the current code realize the intended architecture: a modular
composition of **backends + frontends**, connected by **transports**, orchestrated
by a single **AppRuntime**, with an **inline/source** authoring layer on top that
compiles down to a **RunSpec**, and **AppSpec** as the authoritative app description.

Verdict in one line: **the skeleton is faithful, the joints leak.** The hard
structural wins (core layering, actor unification, relay-as-behavior, RunSpec
pipeline) genuinely landed. The parity gaps are concentrated in four places: the
AppSpec read-only contract, the orchestrator forking into two implementations,
the source layer's unkept "one customization point" promise, and the notebook
render-process path being env-switch/branch ad-hocery rather than declared topology.

---

## Scorecard by layer

| Layer | Vision fidelity | Worst issue |
|---|---|---|
| Core layering (core ↛ backends/frontends) | **Strong** | Clean — zero violations, even deferred |
| Actor / role / relay model | **Strong** | `FrontendRelayBase` referenced but absent (minor) |
| Host placement | **Strong** | One unparented `NotebookFrontendHost` in jupyterlab variant |
| Transport decoupling | **Partial** | Routing *policy* lives in the transport, not a relay actor |
| Routing / topology | **Partial** | Multi-target works, but only via the policy-in-transport violation |
| Orchestrator / AppRuntime | **Weak** | Two divergent orchestration paths; AppSpec mutated live |
| AppSpec vs RunSpec | **Weak** | AppSpec is a shared mutable blackboard, not read-only |
| Inline / source authoring | **Partial** | Two customization points; ~80% neuron/jaxley copy-paste |
| Notebook render-process decomposition | **Weak** | Hidden env switch drives a 4-way runtime branch |
| Config-matrix honesty | **Mostly OK** | Plain T3 notebook credible; render-process variant is not first-class |

---

## What genuinely landed (don't relitigate these)

- **Core layering law holds.** No `core/` → `backends/`/`frontends/` import,
  not even deferred. Confirmed by targeted grep + broad token scan. `core/hosts.py`
  correctly retains only core constructs.
- **Actor model unified.** `core/actor.py:36-42` — both `emit_update` and
  `emit_command` on `ActorBase`. `ActorRole` is BACKEND/FRONTEND only; RELAY gone.
- **Relay is behavior, not identity.** `relays/base.py:16` `RelayMixin` is
  parentless; `BackendRelayBase(RelayMixin, BackendBase)` MRO valid; no role-based
  relay detection anywhere.
- **Hosts in the right packages.** `BackendHost`/`ThreadBackendHost` in
  `backends/host.py`, `FrontendHost` in `frontends/host.py`, plain imports.
- **The notebook-Stop bug is structurally fixed.** `ThreadBackendHost(BackendHost)`
  inherits `StopBackend` handling; notebook Stop now halts the backend thread.
- **Everything (in scope) compiles to a real RunSpec.** No `AppRuntime` is
  constructed outside `core/run.py`; inline/source paths produce real `RunSpec`s.
- **`show()` contract conforms.** Arg-free, auto-detects backend/notebook/desktop.
- **RoutedMessage is agnostic and transparently unwrapped** (`messages.py:71-74`,
  registered for both command+update; receiver sees the inner Message).

---

## Critical / Major findings (prioritized)

### M1 — AppSpec is a shared mutable blackboard, not read-only `[MAJOR]` — ✅ STAGE 1 + 1.5 + 1.6 DONE (1.6: 2026-05-19)
Stage 1.6 closes the remaining tier/parallelism nits flagged by the survey:
- `AppSpec.metadata` mutable bag → moved live to `AppState.metadata` (blueprint
  keeps declared initial); `AppSpecPatch.metadata_updates` folds into AppState.
- `LayoutCatalog.active` → reclassified as **declared default**; live selection
  owned by `AppState.active_layout_id` + `AppState.active_layout()`.
  `RefreshPlanner` takes an `active_layout` resolver; `View3DRefreshContext`
  carries the live `active_layout`. Justified by upcoming NeuroML multi-stage
  layouts (real consumer, not speculative).
- `Geometry` / `MorphologyGeometry` / `GridGeometry` → renamed
  `GeometrySpec` / `MorphologyGeometrySpec` / `GridGeometrySpec` across 16 files
  (pure declarative — suffix now matches the rule).
- `StateBinding` → `StateBindingSpec` (declarative value-reference).
- Zero stale non-`*Spec` references remain in non-deprecated src.


Stage 1.5 (pure spec/state split) shipped: `Field` → `FieldSpec` (declarative,
`initial_values`) + `Field` as runtime value view; `DataCatalog.fields` is
`FieldSpec`-only; `AppState = f(AppSpec)` with `AppState.fields` materialized
from `FieldSpec`. Backends/inline build `FieldSpec`; frontend/visuals read live
values from `AppState.fields`. Verified structurally (no display test). Residual
tier nits (`LayoutCatalog.active`, `AppSpec.metadata`) and the cosmetic
`Geometry`→`*Spec` suffix logged in [m1-appspec-staging.md](m1-appspec-staging.md)
as Stage 1.6 candidates (non-blocking; not leaking post-Stage-1). Stage 2
(orchestrator-authoritative) still deferred. Original finding below.


Target model: (A) orchestrator-authoritative, **sequenced** (see
[m1-appspec-staging.md](m1-appspec-staging.md)). Stage 1 (zero-regret data
split) implemented: new `frontends/app_state.py::AppState` deep-copies the
authoritative AppSpec; `VispyFrontendWindow.app_spec` is now a read-only
property over `self.app_state.spec`; the fold block mutates the copy, never the
orchestrator's object. `AppRuntime.app_spec` documented read-only; no in-process
mutator path to the seed remains (verified: working-copy mutation leaves the
seed untouched). NotebookFrontend was already clean (keeps its own `_buf`,
never folds structurally). Stage 2 (orchestrator fold + rebroadcast + origin
dedup) deferred to the first multi-frontend topology. Original finding below.


`core/runtime.py:28-30` exposes `app_spec` as the live mutable object. The vispy
frontend mutates it every frame: `frontend.py:838-880` (`app_spec.data.fields[...]=`),
`:887-895` (`replace_view/operator/control`), `:897` (`metadata.update`),
`:910-915` (layout patch). The vision says AppSpec is authoritative and read-only
after `AppRuntime` construction; in practice it doubles as live frontend scene
state. This conflates "startup contract" with "runtime scene store" and is the
root cause of the AppSpec/RunSpec separation looking clean structurally but being
muddy in behavior.
**Fix direction:** make orchestrator-held AppSpec immutable; give frontends a
separate derived scene store, or formally redefine the contract as
"immutable authoritative spec + per-actor mutable working copy."

### M2 — Two divergent orchestration paths; the "one orchestrator" is two `[MAJOR]` — ✅ FIXED 2026-05-18
Resolution: `AppHandle.wait()` is now the single launch lifecycle (foreground →
run loop; no-foreground → block until stop/all-subprocesses-exit).
`AppRuntime.wait()` deleted; `run_orchestrator` collapsed to
`start_app(run_spec).wait()`. Direction chosen: consolidate into `AppHandle`
(not `AppRuntime`) because `start_app` already pre-runs non-foreground hosts and
collects the notebook widget result — `AppRuntime.wait`'s daemon-thread model
would double-invoke `run()`. `AppRuntime` remains the AppSpec + stop-signal
owner. Original finding below.


`run_orchestrator` uses `AppRuntime.wait(items)` with try/finally stop
(`run.py:58-62`). `start_app` does **not** call `runtime.wait`; it runs background
actors inline and returns an `AppHandle` whose `wait()` (`hosts.py:285-297`)
**reimplements** the foreground/background split independently of
`AppRuntime.wait()` (`runtime.py:42-67`). Notebook strains it further:
`NotebookFrontendHost.run()` schedules its own asyncio task and calls
`runtime.stop()` directly (`notebook_host.py:561-583`) — AppRuntime degrades to a
passive stop-flag holder. **The single central orchestrator is, as built,
insufficient** — the code already needs per-environment runners.
**Fix direction:** `AppHandle.wait()` delegates to `AppRuntime.wait()`; one
orchestration implementation, environment differences expressed as host policy.

### M3 — Routing policy lives in the transport, contradicting its own design doc `[MAJOR]` — ✅ FIXED 2026-05-19
Resolution: routing fully extracted from the transport layer; transports are
now pure channel mechanisms (`PipeEndpoint` over multiprocessing pipes or
in-process queues), zero payload/role/intent inspection. Routing moved into
a new framework infrastructure piece — **the Bus** ([core/bus.py](src/compneurovis/core/bus.py)) —
which is **NOT an Actor** and does not appear in the user's actor hierarchy.
The Bus is always present, inserted by the orchestrator between every pair of
peer actors (star topology). Its routing rules: (1) explicit `RoutedMessage`
envelope wins; (2) per-id `RelaySpec` rules; (3) default = broadcast to every
other peer. Critically, direction is **never** inferred from actor role —
backend can emit commands, frontend can emit updates, the Bus delivers per
the rules. To avoid the proliferation of discriminated kinds, **no `RELAY`
role** was introduced and **no `RelayBase` class** was added. `RelayMixin` and
`BackendRelayBase` were deleted; their `emit_routed`/`emit_command_routed`/
`emit_update_routed` helpers were folded into `ActorBase` (any actor may
address a specific peer). `ComposedBackend` is now a plain `BackendBase`
(it was never structurally a relay — just a backend that wraps sub-backends
internally). `transports/routed.py` deleted; `relays/` directory deleted.
The transport factory signature now returns a `BusFabric{peer_endpoints, bus}`
which `run_orchestrator` unpacks: peer endpoints wire to each actor's host,
the Bus runs in its own daemon thread (`BusThread`) inside the orchestrator
process. Verified: AppSpecSnapshot routes via default broadcast, RoutedMessage
envelope delivered + unwrapped transparently. Original finding below.


`transports/routed.py:8-9` imports `ActorRole`/`ActorSpec`/`RelaySpec`;
`_RoutingMixin._route` (`:30-41`) branches on payload types (`SetControl`,
`InvokeAction`) and `intent=="update"` to pick default targets. The transport is
interpreting message *meaning* — exactly what the vision forbids, and
`app.py:415-419`'s own docstring says RelaySpec routing "lives in the relay
actor, not the transport." The `RoutedMessage` envelope path is clean; the
role/intent fallback is the violation.
**Fix direction:** `_route` handles only the `RoutedMessage` envelope; move
default-target resolution into a relay actor.

### M4 — Source layer has two customization points, not one; heavy duplication `[MAJOR]`
The vision promises one source = one clean `_make_backend`. Reality
(`inline/sources.py`, `backends/{neuron,jaxley}/attach.py`):
- Every source must also override `_build_app_spec_for_backend` — a second
  customization point; `InlineSource`/`ComposedSource` even discard the `backend`
  arg (`sources.py:166-167`).
- Control/action dispatch is **quadruplicated**: `InlineBackend.handle`
  (`inline/backend.py:56-71`), `ComposedBackend.handle` (`:110-132`), and the
  near-identical `_AttachBackend` blocks in `neuron/attach.py:150-172` and
  `jaxley/attach.py:158-183`.
- neuron/jaxley attach files are ~80% copy-paste: `_append_morphology_and_history_views`
  verbatim in both; `MorphologyBinding`/`SegmentHistoryBinding` dataclasses
  duplicated; `NeuronAppSpecBuilder`/`JaxleyAppSpecBuilder` near line-for-line.
**Fix direction:** shared control/action dispatch mixin consumed by all four
backends; one shared morphology/history bindings module; collapse to a single
`_make_backend` with the backend owning `build_startup_app_spec`.

### M5 — Notebook render actor is branch-synthesized, not declared topology `[MAJOR]`
`_source_runtime.py:163-205`: one env var (`CNV_NOTEBOOK_RENDER_PROCESS`,
read only at `:210-214`, set inside the notebook itself) drives a 4-way fork —
actor list (`:187-200`), routing targets (`:164`), frontend mode (`:179`),
transport mode (`:205`). The vision wants frontend decomposition expressed as a
normal declared multi-actor RunSpec. It is hidden special-case branching with no
public API surface.
**Fix direction:** first-class frontend-decomposition option on the source/RunSpec
(e.g. a frontend profile) that *declares* the renderer actor + routing; derive
topology from declared actors, not an `if`.

### M6 — Notebook widget host welded to morphology + a named "renderer" actor `[MAJOR]`
`notebook_host.py:78` hardcodes `_display_field_id="segment_display"`; `:213`
only accepts a `RenderedFrame` with that id; `:257-291` builds morphology camera
semantics inline; `:293-327` hardwires `RoutedMessage("renderer", …)`;
`:608-616` host-level coalescing special-cases `CameraCommand` by `.kind`. The
vision wants a generic rendered-frame consumer + generic camera/interaction
emitter. Currently it knows the renderer's actor id and that it's a morphology
orbit target.
**Fix direction:** generic frame-stream + camera contract; morphology scene
knowledge moves to the VisPy render actor.

### M7 — Headless `run_app` returns instantly instead of blocking until stop `[MAJOR]` — ✅ FIXED 2026-05-18
Resolution: fixed together with M2. `AppHandle.wait()` no-foreground branch now
blocks until `runtime.is_stopped()` or all hosted subprocesses exit (with
KeyboardInterrupt → stop). Foreground-count validation is now uniformly covered
by `start_app` (`run.py:80-84`) for every entry point since `run_orchestrator`
routes through `start_app`. Original finding below.


`start_app` returns immediately (`run.py:108`); `AppHandle.wait()` returns early
when there is no foreground actor (`hosts.py:291-292`). Only
`run_orchestrator`'s `runtime.wait()` honors the headless poll-until-stop loop
(`runtime.py:60-64`). So headless via `run_app` contradicts the vision
("headless run still blocks until stop/all-finish"); behavior is inconsistent
across entry points. Related: "0 or 1 foreground" is validated in `start_app`
(`run.py:80-84`) but **not** in `run_orchestrator`/`AppRuntime.wait()`
(`runtime.py:56-57` silently takes `foreground[0]`).
**Fix direction:** validate foreground count in `AppRuntime`; unify the
headless-blocking semantics across entry points.

### M8 — No frame-stream policy / backpressure / message delivery classes `[MAJOR, vision-acknowledged]`
`messages.py:118-125` `RenderedFrame` carries only `data/format/width/height` —
no quality/rate/priority/coalescing. Rate control is scattered ad-hoc constants
(`notebook_host.py:42-43` `RENDER_HZ`/`REMOTE_MORPHOLOGY_FRAME_HZ`, `:476`
hardcoded JPEG q70, `:215-217` wall-clock drop). No ack/backpressure; no delivery
classes anywhere. This is on the vision's own known-gap list — recorded here as
confirmed, not as a surprise. It blocks the notebook render-process path from
being default-able.

---

## Minor findings

- **Hardcoded perf-log debug block — flagged by two independent agents.**
  `backends/host.py:103-121`: `ThreadBackendHost.step()` is overridden *solely* to
  append timing to a hardcoded absolute path
  `c:\Users\orren\...\scratch\perf_stats.txt` every 60 steps, opening/closing a
  file in the hot loop, duplicating `BackendHost.step()`, and bypassing the
  project's `core/_perf` facility. Dev scaffolding in framework code on the
  bleeding-edge path — **remove before shipping.**
- **`RunSpec.routing` is a dead second source of truth.** `run.py` never reads it;
  every call site passes routing twice — into `routed_transport(routing)` and as
  `RunSpec.routing=` (`_source_runtime.py:138-139`, `notebook_host.py:696-697`).
  Can silently diverge. Delete it or have `run.py` inject it into the factory.
- **`run_as_backend`/`run_as_frontend` are `NotImplementedError`** — ✅ FIXED 2026-05-19.
  Both are now real local primitives: take an actor source + a
  `TransportEndpoint`, build the appropriate host (`BackendHost` /
  `FrontendHost`), and run the step loop until stop. `run_orchestrator(spec)`
  was lifted into a true primitive (open fabric + create `AppRuntime`, NO
  spawn) returning an `AppHandle` with `endpoints`/`actors`/`runtime` and
  empty `items`. `start_app(spec)` is now literally
  `run_orchestrator(spec) + for each actor: spawn via host_source(runtime,
  endpoint)` — the bundled composition. `run_app = start_app(...).wait()`.
  `_source_runtime.run_source_backend` delegates to `run_as_backend`, so the
  ScriptBackendProcess subprocess and a future remote backend worker go
  through the **same** code path. One model, full composability: bundled and
  distributed differ only in *who spawns the client*, not in framework code.
- **`ConnectionSlotHost` has no accept loop** (`hosts.py:61-79`) — placeholder
  until WebSocket transport exists. Fine for now, won't function for real dial-in.
- **`RunSpec.app_spec` is `Optional` but always required** at runtime
  (`run.py:44-45,75-76`). Make non-optional or validate in `__post_init__`.
- **No per-update-type routing.** All updates go to `default_update_targets`
  indiscriminately (`routed.py:31`); can't route `RenderedFrame` and `StatePatch`
  to different frontends. Only commands have per-id routes.
- **Silent unknown-target no-op.** A RelaySpec target referencing an unknown
  actor id silently drops (`routed.py:108-109/165-166`); no validation.
- **`FrontendRelayBase` referenced but absent.** `relays/base.py:21,45` docstrings
  mention it; only `BackendRelayBase` exists/exported. Stale doc or missing
  symmetric class.
- **`NotebookFrontendHost` (jupyterlab variant) has no base class.**
  `frontends/vispy/notebook_host_jupyterlab.py:35` — duck-typed host; should
  derive `FrontendHost` or be confirmed not a host.
- **Stale "adapter" wording in authoring layer.** User-facing error
  `inline/sources.py:316` ("…or a CompNeuroVis adapter."), docstring `:152`,
  `adapter` local vars in `inline/__init__.py`. Vision dropped "adapter" for
  "source"; tree has no `adapters/` dir (doc says `adapters/base.py` — doc stale,
  tree shape is the better one).
- **`print()` in geometry build hot path** — `backends/.../app_spec.py:115`
  (`print("Meta file generated…")`). Route through diagnostics.
- **No startup-AppSpec handshake gate.** — ✅ RETIRED 2026-05-19. Backend is
  now authoritative: `BackendHost.start` emits `AppSpecSnapshot(app_spec)`
  after actor init; the multiprocess desktop frontend starts `app_spec=None`
  (loading state) and adopts the snapshot when `app_state is None`.
  `build_desktop_run_spec` no longer builds model+geometry in the main process
  — that was a full duplicate build (symptom: "Meta file generated" printed
  twice on `python scratch/hh_neuron_attach.py`). `RunSpec.app_spec` /
  `AppRuntime.app_spec` now allow `None`; routing falls back to role-based
  (empty `RelaySpec`). Notebook (`ThreadBackendHost`, in-process, single
  build) is unaffected by design.

---

## Config-matrix honesty check

- **T3 notebook (thread, in-process, attach) marked 🔧 — credible.** Default
  `use_render_process=False` branch gives `ThreadBackendHost` + single
  `NotebookFrontend` over inprocess transport; Stop works; authoring matches the
  working desktop scratch scripts.
- **The render-process notebook variant is NOT first-class.** It works only
  through the env-switch + 4-way branch (M5), with extra-actor Stop hand-wired in
  the notebook host (`notebook_host.py:571-577` manually sends a second
  `RoutedMessage("renderer", StopBackend())`), and the perf-log side effect.
  Any matrix row presenting render-process decomposition as first-class
  overstates the code.
- Scratch reality: `scratch/hh_neuron_notebook.ipynb` (+ jaxley twin) is the
  bleeding-edge render-process case; only ad-hocery is the cell-0 env toggle and
  the branching behind it. `hh_neuron_attach.py` / `hh_*_inline.py` /
  `sine_wave_inline.py` are the clean desktop references and are unaffected by
  the render path.

---

## Recommended remediation order

1. **M2 + M7** — unify orchestration: `AppHandle.wait()` delegates to
   `AppRuntime.wait()`; one foreground-validation and headless-blocking semantics
   for all entry points. (Restores the "one central orchestrator" claim.)
2. **M1** — decide and enforce the AppSpec contract (immutable spec + separate
   frontend scene store). This is the deepest conceptual leak.
3. **M3 + dead `RunSpec.routing`** — move routing policy out of the transport
   into a relay actor; single routing source of truth.
4. **M5 + M6 + M8** — make notebook frontend decomposition a declared topology
   with a generic frame/camera contract and an explicit frame-stream policy
   (these three are one body of work).
5. **M4** — collapse the source layer to one customization point; kill the
   neuron/jaxley copy-paste with shared dispatch + bindings modules.
6. Minor sweep — **delete the hardcoded perf-log block first** (it ships dev
   scaffolding), then the stale "adapter" wording, `RunSpec.app_spec` optionality,
   missing validations.

## Open question the user raised: is one central orchestrator possible?

The code says: **not as a single blocking implementation.** It has already
forked into Qt-blocking (`AppHandle.wait`), notebook-async
(`NotebookFrontendHost.run` + own asyncio task + direct `runtime.stop()`), and
subprocess-transport-only (no orchestrator in the child, coordination is purely
message-based). A single *logical* orchestrator (one `AppRuntime` owning
app_spec + stop + threading policy) remains viable and worth keeping — but its
`wait()`/lifecycle must become the *one* implementation that the
environment-specific hosts plug into, rather than each environment
reimplementing the wait/stop dance. Until M2 is fixed, "one central
orchestrator" is aspirational, not actual.
