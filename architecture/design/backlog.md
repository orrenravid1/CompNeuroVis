---
title: Backlog
summary: Deferred one-off ideas that don't yet belong to a phase or proposal. Cross-links the work now owned by Design Directions and the Authoring Layer proposal rather than duplicating it.
---

# Backlog

Deferred ideas. Add new ones with a `Phase:` tag. For sequencing see
[Roadmap](roadmap.md); for the detailed forward record see
[Design Directions](design-directions.md); for the reasoning behind settled choices
see [Design Decisions](decisions.md). Large multi-step plans get their own doc under
`proposals/` and are linked from here.

**Last reconciled with code: 2026-07-11.** This backlog holds only items *not* yet
owned by a proposal or a Design Directions section — those are cross-linked below so
there is one source of truth.

---

## Now tracked elsewhere (cross-links, not duplicated)

| Was a backlog item | Now lives in |
|---|---|
| Frontend layout system (grid → split-tree, sizing, saved layouts) | [Design Directions §4](design-directions.md) |
| Runtime panel layout updates (`PanelPatch` / `LayoutReplace`) | [Design Directions §4](design-directions.md) |
| Plot config model (sync, grouping, ring buffers, decimation) | [Design Directions §5](design-directions.md) |
| Live-update backpressure and coalescing | [Design Directions §5](design-directions.md) (bus-side coalescing landed) |
| Canvas backend and rendering performance | [Design Directions §5](design-directions.md) |
| Remote frontend / alternate (WebSocket) transport | [Design Directions §3](design-directions.md); [Widget Authoring Architecture §7](widget-authoring-architecture.md) |
| Controls density and layout policy | **Resolved** by the control-panel work recorded in [Widget Authoring Architecture](widget-authoring-architecture.md) |
| Built-in binding / capability registry | [Design Directions §6](design-directions.md) (`Feature` bundles) |
| Backend/Transport/Frontend runtime naming | **Done** — the rename landed (`AppSpec`, actors, `ValueChange`) |

---

## Open items

### General graph geometry and 3-D network presentation

Phase: 2 · Network2D is implemented. Treat generalized graph geometry, layout
algorithms, or a future 3-D network presentation as ordinary component work under
the [Widget Authoring Architecture](widget-authoring-architecture.md).

Explored in `scratch/vispy_graph_exploration.py`. `vispy.visuals.graphs.GraphVisual`
+ `NetworkxCoordinates` are viable as the rendering primitive for connectivity views.

- **Potential `GeometrySpec(kind="graph")`:** node positions `(n, 2|3)`, node ids and
  type labels; edges as adjacency or edge list `(m, 2)` with optional weights/types.
  Topology is structural; time-varying node activity lives in a `Field` over
  `("node",)`, so activity coloring is a `FieldReplace`, not a layout rebuild.
- **Potential graph view kind:** references graph geometry plus optional color
  field; `projection` `"2d"` (PanZoom) or `"3d"` (Turntable/Arcball);
  `layout_algorithm` (`spring`/`circular`/`kamada_kawai`/`shell`, or animated
  `force_directed`); `directed`; node/edge style as view props.
- **Interaction:** node click uses an entity-result `ClickSpec`, consistent with
  morphology; selection may drive a `ValueBindingSpec` on `face_color` when that
  widget explicitly opts into highlighting.
- **Benchmark:** a layered-circuit connectivity viewer with per-node live activity
  colored from a Jaxley/NEURON multicell run.

Network2D and the point-cloud fixture already prove registry authoring. Continue
only when a concrete 3-D or algorithmic graph use case requires it.

### Coupled backend / co-simulation ports

Phase: 3

A neural simulator and a body-physics engine exchanging state while running (the
C. elegans case: neural state drives muscles; physics feeds back contacts, stretch,
pose, force). Modeled as **backend composition**, not frontend/transport coupling —
consistent with "no `ComposedBackend`; backends are peers." Target: a `CoupledBackend`
(or peer backends with typed ports) owning a neural adapter, a physics adapter, typed
internal ports (motor/contact/stretch/pose/sensory), and a coupling policy for
timing/authority. Unity is `UnityFrontend` when it renders, a physics adapter when it
simulates. Wait for a concrete embodied example before fixing port/timing semantics.

### Notebook host as a first-class frontend

Phase: 3

A generic experimental notebook frontend now exists, but it is not part of the
supported alpha surface. Its frontend-local RunSpec topology has no environment
fork or widget-specific actors; one generic subprocess reuses registered Vispy
panel lifecycles so live refresh work stays off the kernel, and the shell exposes open
ipywidget control/action presentation registries. Promotion still needs 3-D camera
and picking input, desktop-layout parity, broader notebook-environment testing,
and release hardening. See the
[Widget Authoring Architecture](widget-authoring-architecture.md).

### Cloned / mirrored views

Phase: 2

Mounting the same `view_id` in multiple hosts is normalized away today. The higher-
value direction is probably not literal duplicate mounting but low-friction *cloned*
views over the same field + geometry, with optional camera/presentation sync across
sibling panels. Investigate with real app cases before widening the host/view
contract.

### Repo-local MCP server

Phase: infrastructure

A stdio MCP server exposing this repo's own tooling as MCP tools/resources: run
compile/test/docs checks; query the skills catalog, public API index, and roadmap;
parse SWC, inspect a
serialized `Field`, list examples. Register in `mcp.json` alongside external servers.
Higher value once the public authoring API is stable enough that the repo's surface
is worth exposing formally.

### Shared graph memory across agents

Phase: infrastructure

A committed graph-based MCP memory (`@modelcontextprotocol/memory` over a
git-tracked `memory.json` under `.compneurovis/`) so typed relationships between
decisions are queryable and all agents share one memory. Worth it once decisions
accumulate faster than prose can track, or multiple agent families contribute.

### Harness-governed agent infrastructure proposals

Phase: infrastructure

If non-owner contributors become common, agents use a proposal-only model for
protected surfaces (`skills/**`, `AGENTS.md`, repository-hygiene checks, CI,
policy artifacts) with an `observed → accepted → rejected → implemented` lifecycle.
Current solo-owner workflow is sufficient; revisit when needed.

### Potential Zensical migration

Phase: indefinite

Stay on MkDocs + Material + mkdocstrings until Zensical is stable enough to preserve
strict local builds and the generated API-doc workflow. It can consume `mkdocs.yml`,
which lowers migration cost if it matures.

---

## Completed

- **Backend/Transport/Frontend rename** — `Scene`/`Session` → `AppSpec`/actor,
  `SetControl` → `ValueChange`; the message protocol and package layout landed.
- **Action dispatch + interaction model** — actions and interactions are ctx-first
  callbacks with shared dispatch; the old per-base action-handling mismatch is gone.
- **Startup layout** — a source declares panels/views + `cnv.layout` up front and
  launches via `cnv.show()`, so the window opens into the intended layout (replaces
  the old `startup_scene` hook).
- **Audit skills** — `audit-code-smells`, `audit-layer-boundaries`, `plan-refactor`
  (note: skills as a whole are stale vs. the current architecture and are part of the
  alpha cleanup).

---

## Cleanup / retirement

Phase: 2

- Voltage-specific field ids treated as architectural concepts. Low-level
  `segment_display` / `segment_history` names are only role conventions;
  source-authored widgets may own unique fields (see
  [Design Decisions](decisions.md)).
- Any assumption that a default backend implies morphology coloring is voltage.
- Any user-facing workflow that requires understanding transport boundaries to place
  code correctly.
- Temporary flat-grid layout as the conceptual model (→ layout workbench,
  [Design Directions §4](design-directions.md)).
- `CompositeBackendActor` as anything more than a co-location host
  ([Widget Authoring Architecture §7](widget-authoring-architecture.md)).
