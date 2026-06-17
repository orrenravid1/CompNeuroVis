---
title: Backlog
summary: Deferred features, infrastructure ideas, and cleanup items. Freely editable — add new items with a Phase tag.
---

# Backlog

Deferred work items. Add new ideas here with a `Phase:` tag. For active priorities and what's in flight, see [Roadmap](roadmap.md). For the reasoning behind architectural choices, see [Design Decisions](decisions.md).

Large, multi-step feature plans should not live only as oversized backlog
entries. Put the detailed plan under `docs/architecture/design/proposals/` and
link it here so the backlog stays scannable.

**Phase tags:** `Phase: 2` · `Phase: 3` · `Phase: infrastructure` · `Phase: indefinite`

---

## Visualization Features

### Network / Graph Plotting (2D and 3D)

Phase: 2

Explored in `scratch/vispy_graph_exploration.py`. `vispy.visuals.graphs.GraphVisual` + `NetworkxCoordinates` are viable as the rendering primitive for connectivity views.

**New geometry type: `GraphGeometry`**

- Nodes: positions array `(n, 2)` or `(n, 3)`, node ids, node type labels, optional user-facing labels.
- Edges: adjacency matrix or edge list `(m, 2)`, edge weights or types as optional metadata.
- Topology is structural and does not change frame-to-frame; time-varying node activity belongs in a `Field` with dim `("node",)`.
- A `Field` with per-node values maps cleanly onto vispy `face_color` per node — activity-based coloring requires only `FieldReplace` on the color field, not a layout or adjacency rebuild.

**New view spec: `GraphViewSpec`**

- References a `GraphGeometry` and an optional color `Field`.
- `projection`: `"2d"` (PanZoomCamera) or `"3d"` (TurntableCamera / ArcballCamera).
- `layout_algorithm`: `"spring"`, `"circular"`, `"kamada_kawai"`, `"shell"` (static, via `NetworkxCoordinates`) or `"force_directed"` (animated settling via `fruchterman_reingold`).
- `directed`: bool — enables arrow decoration on edges.
- `animate_layout`: bool — enables timer-driven force-directed settling; stops automatically when the layout converges.
- Node size, node border, edge line width, and arrow style are view-level style props, not data.

**2D vs 3D distinction**

- 2D graphs: `PanZoomCamera`, node positions normalized to `[0, 1]²`, layout computed by NetworkX or vispy's force-directed.
- 3D graphs: `TurntableCamera`, z-positions either computed by a 3D layout (e.g. `nx.spring_layout` with `dim=3`) or supplied explicitly in `GraphGeometry`. The same `GraphVisual` rendering primitive applies; only the camera and coordinate dimensionality change.
- Both cases share one `GraphViewSpec` class distinguished by the `projection` field, consistent with how other views express rendering intent rather than data-model differences.

**Live coloring without layout rebuild**

- `graph_node._node.set_data(face_color=new_colors)` updates per-node colors in place without rebuilding adjacency or re-running layout.
- The correct protocol path is `FieldReplace` on the color field; the graph panel renderer maps it to `set_data(face_color=...)`.
- `FieldAppend` is not meaningful for a per-node scalar field; `FieldReplace` is the right update type here.

**Interaction**

- Node click should emit `EntityClicked(entity_id)` using the node id, consistent with morphology click semantics.
- Selection state lives in the frontend `state` dict and can drive a `StateBinding` on `face_color` or node border for highlight rendering.

**Benchmark app**

- A connectivity viewer showing a layered circuit with per-node live activity coloring (e.g. from a Jaxley or NEURON multicell run) is the natural benchmark for this feature.

---

### Plot Configuration Model

Phase: 2

`LinePlotViewSpec` now supports multiple line-plot panels, rolling windows, and
fixed y-ranges. Remaining work is more about synchronization, grouping, and
high-volume live history behavior than basic multi-plot support:

- shared x-range, cursor, or playback synchronization across multiple plot panels
- selectable traces
- plot grouping
- independent y-axes or stacked plots
- frontend-side ring buffers for very large live fields if simple append-and-trim becomes a bottleneck
- richer incremental plot update paths when reslicing whole fields becomes too expensive for dense multi-trace live plots
- a true bounded live-history storage path so high-frequency `FieldAppend` traffic does not require full `np.concatenate` growth work on every frontend poll
- viewport-aware decimation or other draw-throttling for dense live traces once the visible rolling window still contains more points than pyqtgraph can redraw smoothly at target frame rates
- an explicit history-capture policy so plots can choose between current-state streaming plus selected-trace buffering vs full all-entity history capture for retrospective selection and replay

---

### Frontend Layout System

Phase: 2/3

Current layout already uses explicit `PanelSpec` hosts plus a simple row-major
`panel_grid`. The remaining layout work is about richer topology and sizing,
not about introducing explicit panel inventory from scratch. Future work may
need:

- richer nested panel arrangements beyond the current row-major grid
- explicit row/column sizing policy and persistence
- dockable panels
- collapsible panels
- persistent saved layouts

Detailed proposal:
[Layout Workbench Proposal](proposals/layout-workbench-proposal.md)

#### Implemented: explicit `PanelSpec` hosts plus `panel_grid` on `LayoutSpec`

`panel_grid: tuple[tuple[str, ...], ...]` is live on `LayoutSpec`. Each inner
tuple is a row of panel ids. Empty tuple falls through to `_auto_panel_grid()`,
which derives a default row-major layout from the current `PanelSpec`
inventory.

Example in use (`kenngott_marder_vis_refactor.py`):
```python
panel_grid=(
    (VOLTAGE_PANEL_ID, GATE_PANEL_ID, CURRENT_PANEL_ID),  # all 3 side-by-side
    (CONTROLS_PANEL_ID,),
)
```

Frontend builds nested `QSplitter`s from the grid: vertical outer over rows,
horizontal per row. All named splitters removed; `panel_grid` is the single
layout authority. Panel dispatch is fully generic because every cell is a
`PanelSpec.id`.

**Known limitation — row-major only.** The flat rows-of-cells model cannot express column-spanning layouts. For example, morphology spanning full height on the left with trace and controls stacked on the right:

```
[morphology] | [trace   ]
             | [controls]
```

This requires nesting a vertical splitter inside a horizontal one — a topology the flat grid can't represent.

**Next step: recursive `SplitSpec` over the current explicit panel model.**
Full flexibility now requires keeping `PanelSpec` and adding a recursive
split-tree topology layer, e.g.:

```python
# future direction — not yet implemented
LayoutSpec(
    panels=(
        PanelSpec(id="morph_panel", kind="view_3d", view_ids=("morphology",)),
        PanelSpec(id="trace_panel", kind="line_plot", view_ids=("trace",)),
        PanelSpec(id="controls_panel", kind="controls"),
    ),
    panel_layout=HSplit(
        "morph_panel",
        VSplit("trace_panel", "controls_panel"),
    ),
)
```

`panel_grid` is the current transitional topology interface. A recursive
`SplitSpec` model should replace it once the layout refactor lands, while the
explicit `PanelSpec` inventory remains the panel seam.

---

### Controls Panel Density and Layout Policy

Phase: 2

The controls region now supports scrolling and basic automatic multi-column packing, but the current behavior is still a frontend heuristic rather than a first-class layout policy. Real apps with many sliders and actions need a more explicit way to trade density against discoverability without ad hoc per-example tuning.

Future work may include:

- an explicit controls-layout policy on `LayoutSpec` or a frontend config object so apps can choose `single_column`, `auto_columns`, or fixed `n` columns instead of relying only on width heuristics
- a controls host sizing policy so apps can declare preferred placement and height behavior such as compact scrollable strip vs larger always-visible control area
- a dense or compact controls mode with tighter row spacing and value-label treatment for parameter-heavy scientific dashboards
- optional grouped or collapsible control sections so related parameters stay readable even when the total control count is large
- better coordination between control density and panel layout so line plots and 3-D views remain visually dominant while controls stay accessible

Deferral reason: the current scrollable host plus auto two-column behavior addresses the most immediate screen-height problem, but a high-quality live-plotting library should expose control-density tradeoffs intentionally rather than hiding them behind frontend-only heuristics.

---

### Cloned Views and Mirrored Presentations

Phase: 2

The current layout model does not support mounting the exact same 3-D `view_id` in multiple hosts. Repeated view ids are normalized away, and the frontend assumes a one-view-to-one-host mapping. The more important product question is whether apps need literal duplicate view instances, or whether they really need low-friction duplicate presentations over the same underlying data.

Current investigation suggests the higher-value direction is:

- make it easy to define two or more views over the same field and geometry without repetitive boilerplate
- support optional synchronization of camera or other presentation state across sibling views when authors want mirrored or linked panels
- treat "mirror this panel" as a convenience built on cloned views rather than as a special-case host rule
- revisit true same-`view_id` multi-host mounting only if real apps prove cloned views and optional synchronization are insufficient

Deferral reason: duplicate presentation seems useful, but literal duplicate mounting of one `ViewSpec` is probably less important than better authoring support for cloned views over shared data. That should be investigated and proven with real app cases before the host/view contract is widened.

---

### Default Simulator Scene Builders Always Include a Trace Plot

Phase: 2

`NeuronSceneBuilder.build_scene` and `JaxleySceneBuilder.build_scene` both
produce a morphology view plus a trace/line-plot view, with no opt-out. For
apps that do not use the plot (for example morphology-first debug views), the
unused plot panel is visible and confusing.

The default should be opt-in: morphology-only apps should not have to suppress
or work around a plot panel they did not ask for. The right fix belongs in
Phase 2 alongside the broader feature-composable authoring layer - declaring a
plot should mean adding a feature, not inheriting one unconditionally from the
default simulator builders.

---

## API / Authoring

### Runtime Panel Layout Updates — `PanelPatch` and `LayoutReplace`

Phase: 2

Sessions need to change which controls are visible (e.g. when the user switches between model variants) or add/remove panels at runtime, without triggering a full `SceneReady` that reinitializes all scene data. Two new `SessionUpdate` types address this:

- `PanelPatch(panel_id, control_ids, action_ids, ...)` — surgical update to one panel's contents. Frontend updates the controls widget in place; no panel widget rebuild.
- `LayoutReplace(panels, panel_grid)` — swaps the full panel arrangement. Frontend rebuilds the widget tree but preserves all fields, views, operators, controls, and geometry.

The frontend uses panel id as the stability key. `PanelPatch` patches in place; `LayoutReplace` reconciles by id (stable panels keep their widgets, new panels are created, gone panels are destroyed).

**Enables:** model-variant control switching, multiple controls panels, runtime panel add/remove.

**Does not enable:** adding new controls/actions to the scene (those require `ScenePatch` or a new `SceneReady`).

Detailed design: [Panel Layout Updates Proposal](proposals/panel-layout-updates.md)

---

### Callable-Based Animated Surface Builder

Phase: 2

Writing an animated surface currently requires subclassing `BufferedSession` directly, which exposes session internals to users who just want to express "call this function each frame."

The right Phase 2 primitive is a builder with a callable, `build_animated_surface_app(fn=compute_frame, ...)`, where the session is an internal implementation detail invisible to the author.

- `FuncSession` (a `BufferedSession` that calls `fn()` in `advance()`) is a valid internal implementation of that builder, but should not be a public primitive. It still requires users to think in terms of sessions.
- The builder should also accept `on_control` and `on_action` callbacks so parameter-driven computation remains expressible without a full session subclass.
- Controls that only drive visual properties via `StateBinding` should not need to involve the session at all. The builder should distinguish those from controls that require `send_to_session=True`.

Current workaround: subclass `BufferedSession` directly, as in `examples/surface_plot/animated_surface_live.py` and `examples/surface_plot/animated_surface_replay.py`.

---

### Built-In Binding / Capability Registry

Phase: 2

Reset already exists as a default action in replay and simulator sessions, but
common behaviors still reach the UI through a mix of protocol commands, session
defaults, frontend special-casing, and direct `ActionSpec` wiring. Built-in
behaviors such as reset, pause/resume, and future step/capture/export actions
should become declarative built-in bindings first, and only later a generic
capability system if repeated bindings prove the need.

Intended direction:
- apps or builders opt into built-in behavior declarations
- built-in bindings provide default label, button presence, shortcut, and
  command dispatch semantics
- custom `ActionSpec` remains available for truly app-specific behavior

This should remove frontend special-casing and make common simulation affordances easy to add consistently across examples and real apps.

Related runtime contract:
[Backend, Transport, and Frontend Abstractions](proposals/backend-transport-frontend-proposal.md#capabilities-and-parts)

---

### Base Session Action Dispatch Contract

Phase: 2

`NeuronSession` and `JaxleySession` already treat actions as first-class
semantic commands: they declare `action_specs()`, receive `InvokeAction`, and
dispatch through `_dispatch_action()` into `on_action()` / `apply_action()`.
The generic `Session` / `BufferedSession` base does not provide the same
contract, so custom sessions can expose `ActionSpec` buttons in the UI without
inheriting any default action-dispatch behavior.

Current mismatch:

- frontend controls/actions panels can render arbitrary `ActionSpec` buttons
- frontend sends most actions as `InvokeAction(action_id, payload)`
- backend-specific simulator bases handle that path
- generic `BufferedSession` authors must remember to implement
  `handle(InvokeAction(...))` manually
- `reset` is still special-cased in the frontend as `Reset()` instead of going
  through the same action path

This is a real authoring footgun: action support looks architectural at the UI
layer, but is only guaranteed by some session bases. The public model should
make one of these true:

- every session base that can back a controls/actions panel gets shared action
  dispatch helpers and default `InvokeAction` handling
- or action support is factored into an explicit mixin/capability that builders
  and examples opt into deliberately

The long-term goal is that app authors should not need to remember transport
command trivia just because they added a button.

---

### Interaction System Cleanup

Phase: 2

The current `ActionSpec.selection_mode` path proved useful as a capability check, but it is too rigid as the default public interaction model.

Long-term direction:
- keep richer controller/tool internals available
- prefer callback-driven or declarative-simple interaction hooks for common app authoring
- avoid baking one workflow model into `ActionSpec`

Near-term priority: simplify the public authoring layer so real apps like the external pharynx workflow and signaling cascade can be expressed with mostly defaults, concise configuration, and small semantic callbacks.

---

### Backend / Transport / Frontend Runtime Naming

Phase: 2

The current runtime already behaves like a `Backend <-> Transport <->
Frontend` system, but the public and internal vocabulary still exposes
`Session`, `SessionCommand`, `SessionUpdate`, `PipeTransport`, and
`VispyFrontendWindow` before the simpler mental model. That makes the core
architecture harder to explain than it needs to be.

The next cleanup should introduce explicit `Backend`, `Transport`, and
`Frontend` protocols through a direct breaking rename, not a long compatibility
layer. Current sessions should become backend classes, `PipeTransport` should
satisfy the transport protocol, and `VispyFrontendWindow` can remain the current
desktop frontend implementation while gaining a narrow `Frontend` protocol.
The transport-facing shape should be a thin typed `Message` whose `intent`
starts with command and update semantics. The concrete command/update
dataclasses should remain precise as typed payload schemas, with registered
message types carrying payload type and allowed-intent metadata. Transport
bookkeeping such as ids, correlation ids, and delivery modes should stay out of
the core `Message` until real transports force an envelope or policy layer.
`Scene` is split into `AppSpec` catalogs so the app contract stays declarative,
not shared mutable runtime state. The same proposal reserves `ResourceRef` and
`Snapshot` for a later state/resource plane, and reserves `Capability` until
concrete trace, control, selection, and morphology bindings prove a shared
package contract. Runner or `AppRuntime` lifecycle code stays out of the core
ownership model.

Detailed proposal:
[Backend, Transport, and Frontend Abstractions](proposals/backend-transport-frontend-proposal.md)

Authoring proof:
[Composable Authoring Proof](proposals/composable-authoring-proof.md)

Deferral reason: this should happen as a planned naming/protocol refactor, not
as incidental churn during unrelated feature work.

---

## Infrastructure

### Live Update Backpressure and Coalescing

Phase: infrastructure

The current live-update path can still build UI latency when a worker emits incremental updates faster than the frontend can consume and redraw them. Narrow typed updates exist, but the transport and frontend still need stronger throughput controls for a library that aims to support high-performance live plotting.

Frontend-owned presentation cadence is now partially implemented for line
plots, live 3-D views, and state graphs. Dirty line plots, dirty 3-D views, and
dirty state graphs are presented on capped schedules by default, with
`LinePlotViewSpec.max_refresh_hz`, `MorphologyViewSpec.max_refresh_hz`,
`SurfaceViewSpec.max_refresh_hz`, and `StateGraphViewSpec.max_refresh_hz` as
the current per-view override seams. The frontend also now budgets how many
dirty views it presents in one flush so one hot live panel does not monopolize
the UI thread. That removes one major app-author burden, but it does not yet
solve transport-level backpressure or generalized drop/merge policy for all
update classes.

Current workaround patterns are now visible in real examples: sessions such as
the HH point model and signaling cascade batch multiple solver steps into one
display update so they do not emit one tiny `FieldAppend` per `fadvance()`
call. That is the right app-level control seam for simulation cadence, but it
also exposes a shared architectural cost: append-heavy live fields still pay
repeated array-growth work in the generic append path.

Future work may include:

- explicit backpressure or bounded pending-update queues so the worker cannot build unbounded GUI lag
- transport-level coalescing of repetitive update bursts beyond simple per-poll batching
- field-level append aggregation policies for live trace fields before they reach frontend mutation
- append-efficient bounded storage for live trace fields so `FieldAppend` does not rely on repeated `np.concatenate` growth in both coalescing and final field mutation
- drop/merge policies for superseded display-only updates where freshness matters more than replaying every intermediate sample
- instrumentation hooks so apps can inspect queue depth, poll cost, redraw cost, and dropped/coalesced update counts during performance tuning

Deferral reason: app-level trimming and current frontend batching remove the worst visible stalls for now, but they do not yet make the live pipeline robust under sustained overload.

---

### Canvas Backend and Rendering Performance

Phase: infrastructure

The current VisPy/Qt embedded canvas path can still block the Qt GUI thread even
when dataflow, history mode, update batching, and view refresh cadence are
properly separated. Current pharynx logs show morphology refresh and commit work
as cheap, while the actual canvas draw path remains vblank-shaped on both
integrated and NVIDIA GPU runs.

Detailed tracking note:
[Canvas Backend and Rendering State](proposals/canvas-backend-rendering-state-2026-06-17.md)

Deferral reason: the current refresh budgeting and latest-state morphology path
are the correct near-term architecture. Alternate canvas paths such as a
`QOpenGLWindow` container or detached GLFW diagnostic need focused experiments,
not a rushed rewrite.

---

### Remote Frontend / Alternate Transport

Phase: 3

The protocol and scene model should stay frontend-agnostic. Future work may add:

- websocket transport
- Unity frontend
- richer remote command/update semantics
- more granular patch/update messages for remote scenes where bandwidth and serialization cost make bundled updates especially expensive

Detailed proposal: [WebSocket Transport Proposal](proposals/websocket-transport-proposal.md)

---

### Coupled Backend / Co-Simulation Ports

Phase: 3

Embodied workflows may need a neural simulator and a body physics engine to
exchange state while the app is running. A C. elegans workflow is the motivating
case: neural state can drive muscles or actuators, while body physics can feed
contacts, stretch, pose, force, or proprioception back into the neural model.

This should be modeled as backend composition, not as frontend/transport
coupling. The target shape is one `CoupledBackend` that
owns:

- neural adapter such as NEURON, Jaxley, MOOSE, or custom Python
- physics adapter such as MuJoCo or Unity physics
- typed internal ports for motor, contact, stretch, pose, and sensory signals
- coupling policy for timing, substeps, transforms, and authority
- optional fields, traces, geometry, and diagnostics exposed to the frontend

Unity should be treated according to role: `UnityFrontend` when it renders the
CompNeuroVis app, and `UnityPhysicsAdapter` when it runs physics that writes
simulation state.

Detailed proposals:
[Backend, Transport, and Frontend Abstractions](proposals/backend-transport-frontend-proposal.md#coupled-backends-and-co-simulation)
and
[Composable Authoring Proof](proposals/composable-authoring-proof.md#coupled-neural-physics-proof)

Deferral reason: the backend/transport/frontend refactor should leave a clean
slot for this, but public co-simulation APIs should wait for a concrete embodied
example so timing and port semantics are not invented in the abstract.

---

### Notebook Host / Python Notebook Compatibility

Phase: 3

The architecture proposal identifies Jupyter notebooks as a desired host, and
the current core model is compatible with that direction. The current concrete
implementation is not notebook-ready, though: `run_app(...)` launches the
PyQt6/VisPy desktop frontend, `AppSpec` has no pluggable transport field,
`PipeTransport` is local Python process/thread IPC, worker-backed sessions need
importable session sources, and the base package currently carries desktop GUI
dependencies.

The right notebook path is a separate host/frontend over the shared
`Scene`/`SessionUpdate` substrate, not reuse of the Qt window inside a notebook.
Likely milestones:

- split import and dependency boundaries so core/protocol imports do not require
  Qt, VisPy, or pyqtgraph
- introduce a real transport seam or notebook host runner before live notebook
  backends are promised
- render static scenes, controls, and line plots with notebook-native widgets
  first
- add live `FieldReplace`, `FieldAppend`, `StatePatch`, and `Status` handling
  with notebook-specific throttling
- defer full 3-D picking, tool parity, and desktop-layout parity until the basic
  notebook host is proven

Current architecture map:
[Runtime Architecture Map](../runtime-architecture-map.md#notebook-compatibility)

Deferral reason: notebook support is feasible, but dependency boundaries,
transport seams, and event-loop behavior need deliberate design before it should
be advertised as a supported host.

---

### Repo-Local MCP Server

Phase: infrastructure

The current MCP setup (`mcp.json`) gives all agents access to external tools. A natural next step is a repo-local MCP server that exposes this repo's own tooling and domain knowledge as first-class MCP tools and resources. Any agent working in this codebase — regardless of which client — would then invoke repo scripts and query repo state through the same MCP interface rather than shelling out or reading files manually.

Candidate tools: run PR-readiness check and return structured results; run architecture invariant checks; run compile check and tests; regenerate indexes or MCP configs.

Candidate resources: skills catalog, architecture invariants, public API index, current roadmap.

Candidate domain tools: parse an SWC morphology file and return segment data; inspect a serialized Field (shape, dims, coords); list and describe available examples.

Implementation path: build as a Python stdio MCP server (no extra infrastructure required); register in `mcp.json` as a local server alongside existing external ones.

Deferral reason: external MCPs cover the most acute gaps now; the local server is a higher-effort, higher-value item that makes more sense once the public authoring API (Phase 2) is stable enough that the repo's own surface is worth exposing formally.

---

### Shared Graph Memory Across Agents

Phase: infrastructure

The current auto-memory system (MEMORY.md + per-agent flat files) is per-user and per-agent. A graph-based MCP memory server committed to the repo would address both gaps:
- typed relationships between memories allow queries like "what design chain led to HistoryCaptureMode?" in a way flat markdown cannot answer
- all agents read from the same committed file, so architectural knowledge is genuinely shared

Viable implementation path: run `@modelcontextprotocol/memory` locally, pointed at a committed `memory.json` under `.compneurovis/`. JSON is git-mergeable; for append-heavy workload, auto-merge succeeds most of the time. Agents pull before starting work, push the updated `memory.json` after a session.

Deferral reason: value scales with accumulated decisions. Worth implementing once architectural decisions accumulate faster than the roadmap's manual prose can track, or once multiple agent families are actively contributing regularly.

---

### Harness-Governed Agent Infrastructure Proposals

Phase: infrastructure

If external or non-owner contributors become common, agents should use a proposal-only model for protected infrastructure surfaces. Proposals stored as structured observation artifacts under `.compneurovis/` with lifecycle: `observed` → `accepted` → `rejected` → `implemented`. Protected surfaces include `skills/**`, `AGENTS.md`, readiness/invariant/config-generation scripts, CI workflows, governance docs, and machine-readable policy artifacts under `.compneurovis/`.

Deferral reason: current solo-owner workflow is sufficient. Revisit once external contributors are common or multiple agent/client families are contributing regularly.

---

### Potential Zensical Migration

Phase: indefinite

The current docs site should stay on `MkDocs + Material + mkdocstrings` until there is a clear stable replacement path. `Zensical` is worth revisiting later because it can consume `mkdocs.yml`, which lowers migration cost if it matures. Migration should be reconsidered only once Zensical is stable enough to preserve strict local builds, predictable local authoring, and the current generated API-doc workflow without repo-specific workarounds.

---

## Skills / Developer Tooling

---

## Cleanup / Retirement

### Transitional APIs and Assumptions to Retire

Phase: 2

- Voltage-specific default field ids as architectural concepts
- Voltage-specific default builder assumptions where they imply morphology coloring is inherently voltage-driven
- Backend-labeled builder mental models where the backend name implies the app shape
- Native attachment APIs that imply users must pass a CompNeuroVis-shaped model
  object instead of native simulator roots, paths, objects, explicit adapters,
  callbacks, or ports
- Any user-facing workflow that requires understanding transport boundaries to place code correctly
- Temporary layout behavior that still encodes "main 3-D view plus one plot plus one control stack" as the conceptual model

---

## Completed

### Session Startup Scene API

Implemented. Sessions can now provide `@classmethod startup_scene(cls) -> Scene | None`. `run_app(...)` uses that hook automatically when `AppSpec.scene` is absent. This allows startup layout, controls, and placeholder fields to be known before worker start, opening directly into the intended view without a loading-only phase.

### `audit-code-smells`

Implemented. Full skill at `skills/audit-code-smells/SKILL.md`. Covers import layer violations, `isinstance` dispatch outside frontend, hardcoded field/view IDs, frontend `setdefault` in `_set_scene`, and session `_ui_state` holding display keys.

### `audit-layer-boundaries`

Implemented. Full skill at `skills/audit-layer-boundaries/SKILL.md`. Mechanically checks all four layers for upward imports with explicit grep commands.

### `plan-refactor`

Implemented. Full skill at `skills/plan-refactor/SKILL.md`. Covers touch-point mapping, execution ordering, verification checkpoints, and follow-on skill flagging.
