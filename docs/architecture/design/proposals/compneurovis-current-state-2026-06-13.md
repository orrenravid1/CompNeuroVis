# CompNeuroVis — Current State of the Repository

**Date:** 2026-06-13
**Branch:** `user/orren/compneurovis-alpha-refactor`
**Released line:** `0.3.0` (2026-05-05); refactor work sits ahead of it, unreleased.
**Reliable surface:** `src/compneurovis/` and a subset of `scratch/`. Other top-level areas (parts of `examples/`, some `docs/`) lag the branch and should be treated as provisional.

This is a factual snapshot of what exists in the repository right now and its status, intended to orient a reader who is picking the project up mid-refactor. It records what is in place, what is in flight, and where the code and the planning docs disagree. For an opinionated assessment and forward-looking recommendations, see the companion analysis document of the same date.

CompNeuroVis is a UI tool for academic computational-modeling workflows: it surfaces interactive views, controls, and live plots over modeling/simulation code. It involves no biology, no wet-lab procedures, and no security concerns; terms like "neuron," "morphology," and "channel" refer only to data shapes, simulator integrations, and visualization panels.

---

## 1. One-paragraph status

The refactor has restructured the project around a single immutable declarative spec (`AppSpec`), a symmetric actor model in which backends and frontends are the same kind of peer, and a generic message bus with explicit routing. The single-backend / single-frontend path works end to end — including inline authoring in scripts and notebooks, with live plotting from NEURON and Jaxley integrations through a Vispy/PyQt frontend. The multi-actor, multi-machine topology is fully expressible in the spec layer but not yet runnable across a network: only in-process and pipe transports exist, the wire protocol still carries live Python objects, and multi-source composition is deliberately stubbed. Several planning documents still describe the pre-refactor `Scene`/`Session` vocabulary that the branch has already replaced.

---

## 2. Repository layout

```
CompNeuroVis/
├── src/compneurovis/        # the package — the reliable surface
│   ├── __init__.py          # public authoring API + lazy optional exports
│   ├── core/                # spec model, actors, bus, runtime, messages
│   ├── inline/              # convenience authoring layer (source/show)
│   ├── backends/            # simulator integrations: neuron, jaxley, inline
│   ├── frontends/           # rendering: vispy (PyQt + notebook hosts)
│   ├── transports/          # inprocess, pipe (no network transport yet)
│   ├── deprecated/          # quarantined pre-refactor builders
│   ├── neuron.py, jaxley.py # thin optional-import shims
│   └── _source_runtime.py   # inline/notebook source launching
├── scratch/                 # explorations; inline/attach examples are reliable
├── examples/                # custom, debug, jaxley, neuron, surface_plot
├── tests/                   # ~25 test modules (see §9)
├── docs/                    # mkdocs site; design/ holds proposals + logs
│   └── architecture/design/proposals/  # refactor logs and feedback live here
├── skills/                  # repo-specific authoring/audit skills
├── scripts/                 # architecture-invariant and docs checks
├── res/                     # sample morphology data (.swc)
└── pyproject.toml           # Poetry; extras: neuron, jaxley, pyqt6, contrib
```

---

## 3. The core model (`src/compneurovis/core/`)

This is the heart of the refactor and the most settled part of the tree.

| Module | Role | Status |
|--------|------|--------|
| `specs.py` | `SpecBase` / `IdentifiedSpec` markers for immutable declarations | Stable |
| `app_spec.py` | `AppSpec` + the four catalogs (`DataCatalog`, `ViewCatalog`, `InteractionCatalog`, `LayoutCatalog`), `PanelSpec`, `LayoutSpec`, and validation | Stable; panel/view vocabulary is closed (see §10) |
| `field.py` | `FieldSpec` (immutable declaration) and `Field` (live value view) | Stable; arrays are defensively read-only |
| `views.py` | `ViewSpec` subtypes: morphology, surface, line plot, state graph | Stable; plotting-oriented set |
| `geometry.py` | `GeometrySpec` and grid/morphology geometry | Stable |
| `controls.py` | `ControlSpec`, `ActionSpec`, value specs | Stable |
| `operators.py` | `OperatorSpec` (e.g. grid slicing) | Stable |
| `messages.py` | Typed command/update payloads, `MessageType` registry, `make_message` | Stable; carries live Python objects |
| `actor.py` | `ActorBase` — the single peer type; emit/handle/tick surface | Stable |
| `bus.py` | `Bus`, `BusThread`, `bus_transport`; explicit routing, no fallback | Stable |
| `run_spec.py` | `RunSpec`, `ActorSpec`, `RoutingSpec`, `RouteSpec`, `MessageMatch` | Stable |
| `run.py` | `run_orchestrator` / `start_app` / `run_actor` / `run_app` launch primitives | Stable |
| `projection.py` | `AppProjection` — actor-local mutable read model | Stable |
| `runtime.py`, `runtime_options.py` | `AppRuntime` and options | Stable |
| `actor_host.py`, `actor_launchers.py` | host loops, script/thread launchers, connection slots | Stable |
| `channel.py`, `bus.py` | per-peer channel abstraction | Stable |
| `state.py` | `StateBindingSpec` — reference into the binding namespace | Present, lightly used |
| `_immutability.py` | `FrozenDict`, `readonly_array` helpers | Stable |
| `_perf.py`, `diagnostics.py` | perf logging and diagnostics | Stable |

Key invariants now enforced in code: specs are immutable (frozen dataclasses plus read-only arrays and `FrozenDict`); `AppSpec` is validated but never normalized in place (grid construction happens in the authoring layer); backends and frontends are both `ActorBase`; the `Bus` is not an actor and never infers direction from role; and unroutable messages raise `BusRoutingError` rather than broadcasting.

---

## 4. Runtime and launch model

A run is a composition of small primitives. `run_orchestrator(run_spec)` opens the transport fabric and creates the runtime but spawns no actors. `start_app(run_spec)` is that plus spawning each actor through its `ActorSpec.host_source`. `run_app(run_spec)` is `start_app` plus blocking until the foreground actor exits. `run_actor(source, channel)` connects a single actor to one channel and is used identically by local launchers and (eventually) remote workers. Actors with no host source get a connection slot held open for a client to dial into — the per-actor mirror of the pure-orchestrator path.

The `AppSpec` is declared to all participants once, by the orchestrator, via an `AppSpecDeclared` update on the bus. Field values are not part of the spec; they flow as `FieldAppend` / `FieldReplace` deltas into each actor's `AppProjection`.

---

## 5. Backends (`src/compneurovis/backends/`)

`BackendBase` is a thin subclass of `ActorBase`. Three integrations exist:

- **NEURON** (`backends/neuron/`) — `NeuronBackend` plus a `NeuronAppSpecBuilder` and an `attach.py` adapter for native NEURON code. Optional; requires the `neuron` extra.
- **Jaxley** (`backends/jaxley/`) — `JaxleyBackend`, `JaxleyAppSpecBuilder`, and `attach.py`. Optional; requires the `jaxley` extra.
- **Inline** (`inline/backend.py`) — `InlineBackend` for pure-Python callable/iterator sources used by the convenience layer.

Both simulator backends follow the same shape: an app-spec builder that lowers a native model into an `AppSpec`, an attach adapter, and a backend actor that steps the simulation and emits field deltas. A shared `history.py` provides replay/history capture.

---

## 6. Frontends (`src/compneurovis/frontends/`)

`FrontendBase` is the frontend peer type. The implemented frontend is **Vispy + PyQt** (`frontends/vispy/`), which includes the windowed host (`VispyFrontendWindow`, `VispyActorHost`), per-panel renderers (`panels/`, `renderers/`, `view3d/`), interaction plumbing (`interaction_context.py`, `interaction_target.py`, `view_inputs/`), refresh planning, and two notebook hosts (`notebook_host.py`, `notebook_host_jupyterlab.py`) plus a remote-frame-buffer widget (`rfb_widget.py`) for in-notebook rendering. The Vispy frontend is optional and requires the `pyqt6` extra.

---

## 7. Transports (`src/compneurovis/transports/`)

Two transports exist: `inprocess` (in-memory channel pairs) and `pipe` (OS pipes between local processes). There is **no network transport** — a WebSocket transport exists only as a proposal. This is the concrete reason the multi-machine topology is not yet runnable.

---

## 8. Inline authoring layer (`src/compneurovis/inline/`)

The convenience surface for the common case. `cnv.source(model)` returns a source object that owns its own `trace`, `control`, and `action` bindings; `cnv.show()` lowers a single source through the same `RunSpec` / `start_app` path as everything else; and `cnv.show(build)` runs a heavier simulation in a child process while rendering in-kernel, so a slow sim cannot starve the render loop. The layer demonstrably lowers into the same `AppSpec` as the rest of the system.

In-flight within this layer: `cnv.compose(...)` and `cnv.remote(...)` accept multiple sources at the authoring level, but `cnv.show()` raises `NotImplementedError` for more than one source, and `ComposedSource` / `RemoteSource` / `RemoteActorRef` lowering is stubbed rather than faked.

---

## 9. Tests, examples, and tooling

The `tests/` directory holds roughly two dozen modules covering the app spec, core bindings, fields and geometry, messages, the NEURON and Jaxley backends and scenes, pipe transport, layout updates, replay, perf logging, packaging metadata, docs/index generation, and PR-readiness. Test depth is uneven — the frontend-binding tests are large, while routing-rule validation and serialization are not yet covered (matching the gaps in §10).

`examples/` contains `custom`, `debug`, `jaxley`, `neuron`, and `surface_plot` directories; treat these as partially behind the branch. In `scratch/`, the reliable entry points are the inline and attach scripts — `sine_wave_inline.py`, `lif_inline.py`, `hh_neuron_inline.py`, `hh_neuron_attach.py`, and `hh_jaxley_attach.py` — which exercise the current authoring surface directly.

`scripts/` includes architecture-invariant and docs checks (`check_architecture_invariants.py`, `check_docs_vocabulary.py`, `pr_readiness.py`, index/MCP-config generators). `skills/` holds repo-specific authoring and audit skills. The project is Poetry-managed with optional extras `neuron`, `jaxley`, `pyqt6`, and `contrib`.

---

## 10. Known in-flight and stubbed areas

- **Closed panel/view vocabulary.** `PanelSpec.kind` is validated against a fixed set (`view_3d`, `line_plot`, `controls`, `state_graph`) and `ViewSpec` subtypes are a fixed plotting-oriented set. Adding a new app type (e.g. an editor or a teacher/student view) currently requires editing core validation rather than registering a kind.
- **Non-serializable protocol.** `AppSpecDeclared` ships the live `AppSpec` object and field deltas carry raw NumPy arrays, so nothing yet crosses a process or machine boundary as a stable wire format.
- **No network transport.** Only in-process and pipe transports exist.
- **Stubbed composition / remote sources.** Multi-source and remote lowering raise `NotImplementedError` by design.
- **Zero-arg inline actions.** `InvokeAction` carries a payload, but inline action functions are still invoked with no arguments.
- **Conflated cadence.** The inline backend runs a fixed ~60 Hz loop; simulation, sampling, flush, and render rates are not yet separable.
- **Session singleton.** The inline session is a module-level singleton; an explicit session object is not exposed publicly.
- **Layout grid is transitional.** Panels use a flat grid; a recursive split-tree "workbench" model is proposed but not implemented.
- **`RenderedFrame` shares the update stream.** Rendered artifacts currently travel as ordinary update payloads rather than a separate output stream.

---

## 11. Documentation drift to be aware of

The branch code is ahead of several planning documents. Most notably, `docs/architecture/design/roadmap.md` and the `CHANGELOG.md` still describe the pre-refactor `Scene` / `Session` / `startup_scene(...)` vocabulary, whereas the code has already replaced these with `AppSpec`, `AppProjection`, `RunSpec`, and the actor/bus model. The roadmap's "Current Transition Targets" remain a good guide to *intent* (composable authoring, separating runtime substrate from app modes, separating simulation cadence from presentation cadence, replacing the transitional layout shell), but its naming should be read as historical. The proposals and the personal refactor log under `docs/architecture/design/proposals/` are the most current written record of the work.

---

## 12. Reading order for a new contributor

1. `src/compneurovis/core/app_spec.py` and `core/field.py` — the declarative model.
2. `core/messages.py` — the command/update vocabulary.
3. `core/actor.py`, `core/bus.py`, `core/run_spec.py`, `core/run.py` — the topology and launch model.
4. `core/projection.py` — how actors hold live state.
5. `inline/` — the convenience layer and how it lowers to `AppSpec`.
6. A reliable `scratch/` script (e.g. `sine_wave_inline.py`) to see the surface in use.
7. The proposals and refactor log under `docs/architecture/design/proposals/` for current direction.
