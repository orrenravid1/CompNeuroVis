---
title: App Configuration Matrix
summary: Golden reference — the taxonomy of every valid app configuration, checked regularly to see whether architecture choices still express the full space.
---

# CompNeuroVis App Configuration Matrix

**Golden reference. Last verified against code: 2026-08-06.**

A taxonomy of every valid app configuration. This is a *standing check*, not a
snapshot: revisit it whenever an architecture choice is on the table. If a
proposed refactor can't express a row in this matrix, the abstraction is wrong;
if a row's status has drifted from the code, the matrix is stale and should be
re-verified. The open transport/topology rows are the same work tracked forward
in [Design Directions §3](design-directions.md); this doc is the "can we still
express every configuration" lens on it.

---

## Dimensions

Every configuration is a point in this space:

| Dimension | Options |
|---|---|
| **Backend environment** | Same process, same-machine subprocess, WSL, remote cloud/server |
| **Frontend environment** | Same process, same-machine subprocess, remote browser, remote notebook |
| **Frontend renderer** | Vispy/Qt, Jupyter notebook (ipywidgets), Unity, Web (WebGL/Three.js), Headless |
| **Transport** | In-process queue, OS pipe, WebSocket, Shared memory |
| **Topology** | 1B:1F, 1B:NF (broadcast), NB:1F (aggregation), NB:MF (mesh) |
| **Interaction role** | Full (owner), Observer (read-only), Partial (constrained controls) |
| **Data source** | Live simulation, Replay, Static/one-shot, External stream |
| **Authoring API** | Inline source (`cnv.source` / `cnv.neuron.source`), RunSpec, Bespoke |

### Widget-extension preservation rule

The widget structure is part of this matrix contract. The
[Widget Authoring Architecture](widget-authoring-architecture.md)
must not optimize only for the currently implemented Python/Vispy rows.

For every widget kind:

- package-owned declaration and renderer code lowers to core-owned, kind-keyed, data-only
  extension specs; canonical `AppSpec` identity does not depend on importing a package-owned
  Python subclass;
- inline authoring lowers through the same `AppSpec`/`RunSpec` path as low-level and
  bespoke authoring;
- discovery and rendering are frontend-local, so a backend or headless process does not need
  a GUI package and another frontend can register the same kind independently;
- frontend host support is also local and registry-driven: Vispy plugins may
  register additional panel kinds without changing core or the frontend window,
  while another frontend may support a different shell taxonomy; core validates
  neutral declarations and unsupported frontends report precise errors;
- controls and actions are panel-owned neutral specs; their authoring and
  presentation kinds use open registries, and no action name has runtime magic;
- visual contributions target a panel and capability directly rather than
  borrowing identity from a first view, preserving viewless and multi-view host
  configurations;
- picking carries an authored selection role, and entity lookup follows that
  selection's exact geometry, preserving overlapping ids and multi-selection views;
- fields and data-source refs work identically for live, replay, static, and external
  producers;
- ids, data refs, selections, operators, contributions, and refresh targets remain
  fragment/actor scoped for T5-T7;
- widget mutation is expressed through the interaction catalog, allowing Full, Observer,
  and Partial roles to be enforced by runtime policy rather than widget-specific code.

This rule does **not** require each widget package to ship every frontend renderer. A
frontend may explicitly report an unsupported kind. It does require the canonical authored
structure and transport meaning to remain renderer- and language-neutral, so adding a
Vispy-only widget today cannot make the Unity, Web, remote, headless, broadcast, or
aggregation rows inexpressible tomorrow.

---

## Topology Catalog

Named topologies used in the matrix below.

| ID | Name | Description |
|---|---|---|
| **T1** | Local single-process | Backend + frontend + orchestrator all in one Python process |
| **T2** | Local multiprocess | Backend subprocess + frontend main process, same machine, OS pipe |
| **T3** | Local thread | Backend daemon thread + frontend in same process (notebook pattern) |
| **T4** | Remote 1:1 | Backend and frontend in separate environments, WebSocket |
| **T5** | Broadcast 1:N | One backend, multiple frontend observers (teacher + students) |
| **T6** | Aggregation N:1 | Multiple backends feeding one frontend (multi-region, multi-cell) |
| **T7** | Mesh N:M | Multiple backends, multiple frontends, arbitrary routing |

---

## The Matrix

### Row key

- ✅ Implemented and tested
- 🔧 Implemented, gaps known (see Notes)
- 🔜 Designed, not implemented
- ❌ Not yet designed
- N/A Not applicable

---

### Vispy/Qt Frontend

| Topology | Backend env | Transport | Authoring | Status | Notes |
|---|---|---|---|---|---|
| T1 | Same process | In-process queue | RunSpec | ✅ | `run_app(RunSpec)` with in-process transport |
| T2 | Subprocess | OS pipe | RunSpec | ✅ | `run_app(RunSpec)` with pipe transport |
| T2 | Subprocess | OS pipe | Inline source | ✅ | `cnv.show()` lowers a source through `run_source_actor` → `run_actor` — the **same** `RunSpec`/`start_app` path (no bypass; Gap 1 closed) |
| T4 | WSL | WebSocket | RunSpec | 🔜 | Transport not built; no stubs remain either (see Gap 4) |
| T4 | Remote server | WebSocket | RunSpec | 🔜 | Same |
| T5 | Subprocess | OS pipe + broadcast | RunSpec | ❌ | Teacher controls Qt; students observe (Qt or other) |
| T6 | Multi-subprocess | OS pipes | RunSpec | ❌ | Multiple backends feeding one Qt frontend |

---

### Notebook Frontend (ipywidgets, VS Code / JupyterLab / classic Jupyter)

| Topology | Backend env | Transport | Authoring | Status | Notes |
|---|---|---|---|---|---|
| T3 | Same process (thread) | In-process queue | Inline source | ✅ | `cnv.show()` in a notebook; the source lowers through the same `RunSpec`/`run_actor` path. Optional in-kernel RFB canvas (`CNV_NOTEBOOK_RFB`) or a render-process split (`CNV_NOTEBOOK_RENDER_PROCESS`) — see note |
| T4 | WSL | WebSocket | RunSpec | 🔜 | Depends on WebSocket transport (Gap 4) |
| T4 | Remote server | WebSocket | RunSpec | 🔜 | Same |
| T5 | Subprocess | Any | RunSpec | ❌ | Teacher notebook (or Qt) + student notebooks as observers |

---

### Unity Frontend

| Topology | Backend env | Transport | Authoring | Status | Notes |
|---|---|---|---|---|---|
| T4 | Python subprocess | WebSocket | Bespoke | ❌ | Unity C# receives field updates; Python runs sim |
| T4 | Remote server | WebSocket | Bespoke | ❌ | Same, backend off-machine |
| T5 | Python subprocess | WebSocket broadcast | Bespoke | ❌ | One sim, Unity + notebook observers |

---

### Web Frontend (browser)

| Topology | Backend env | Transport | Authoring | Status | Notes |
|---|---|---|---|---|---|
| T4 | Python subprocess | WebSocket | Bespoke | ❌ | Browser WebGL renderer + Python sim |
| T4 | Remote server | WebSocket | Bespoke | ❌ | Fully remote |

---

### Headless / Data Export

| Topology | Backend env | Transport | Authoring | Status | Notes |
|---|---|---|---|---|---|
| T1 | Same process | None | RunSpec | 🔜 | Replay backend + file export frontend |
| T1 | Same process | None | RunSpec | 🔜 | Batch run, no UI |

---

### Special Configurations

| Config | Description | Status | Notes |
|---|---|---|---|
| **Static data viewer** | No simulation; renders pre-existing Field/Geometry data | ✅ | Replay backend + Vispy frontend |
| **Bespoke app** | Full custom app (e.g. NeuroML editor) using compneurovis primitives | ❌ | No sugar API; raw `BackendBase + FrontendBase + AppSpec` |
| **Classroom (T5 teacher/student)** | Teacher owns full-control session; students connect as observers with constrained `PartialInteractionRole` | ❌ | Requires 1:N broadcast transport + role-scoped `InteractionCatalog` |
| **Multi-backend aggregation (T6)** | e.g. C. elegans pharynx (muscle physics) + neural model feeding one frontend | ❌ | Multiple `BackendBase` actors, router/aggregator needed |
| **Physics + neuroscience (T6)** | Separate physics and neural backends, shared visualisation | ❌ | Same as above |
| **External data stream** | Frontend observes a live stream not generated by a CompNeuroVis backend | ❌ | Backend adapter wrapping e.g. BrainFlow, Lab Streaming Layer |

---

## Architectural Gaps Exposed by This Matrix

### Gap 1 — Inline/source bypass `RunSpec` — ✅ RESOLVED

`cnv.show()` now lowers a source through `run_source_actor` → `run_actor` (the
same primitive a remote actor uses), and a script backend subprocess spawns via
`runpy.run_path` on the same path. Inline authoring and a hand-built `RunSpec`
share one execution model; the old manual `AppRuntime + Host` wiring is gone.

### Gap 2 — `run_app()` blocking vs. notebook non-blocking — ✅ RESOLVED

`run_orchestrator` / `start_app(RunSpec) -> AppHandle` / `run_app` exist, with
`AppHandle` owning the lifecycle. Desktop blocks on the foreground (Qt) actor;
the notebook path returns without a foreground actor. `run_app` is effectively
`start_app(spec).wait()`.

### Gap 3 — 1:N broadcast transport not built

Teacher/student and multi-observer topologies require a transport that fans out updates to N endpoints. The current `pipe_transport` / `inprocess_transport` are strictly 1:1.

**Fix candidate:** `BroadcastTransport` — one inbound, N outbound endpoints. Frontend role distinguishes Full vs. Observer.

### Gap 4 — No WebSocket transport

Transports are `inprocess` and `pipe` only — both same-machine. No network
transport exists (and no `run_as_backend`/`run_as_frontend` stubs remain either).
The WSL→Windows scenario, Unity/browser frontends, and every remote topology
(T4–T7) block on this. Concrete plan in
[Design Directions §3](design-directions.md); it is the highest-leverage gap
because it unlocks the whole remote quadrant.

### Gap 5 — No N-backend aggregation

Multiple backends feeding one frontend requires a router actor or a compound backend. No design exists yet.

---

## Priority Order (suggested)

Gaps 1 and 2 are closed (single canonical execution model). The open order:

1. **Gap 4** — WebSocket transport. Unlocks the entire remote quadrant of the matrix.
2. **Gap 3** — Broadcast transport. Enables classroom / observer scenarios.
3. **Gap 5** — N-backend aggregation. Enables physics + neural model compositions.

## Notebook Rendering Modes (T3 note)

The notebook thread topology (T3) has three rendering placements, selected by env
flags rather than declared topology — itself a smell tracked in
[Design Directions §7](design-directions.md):

- default: the notebook frontend renders in-kernel.
- `CNV_NOTEBOOK_RFB=1`: the notebook frontend owns a local remote-frame-buffer canvas.
- `CNV_NOTEBOOK_RENDER_PROCESS=1`: morphology/trace rendering runs in a child
  process, keeping heavy draw work out of the kernel.
