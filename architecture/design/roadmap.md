---
title: Roadmap
summary: Where the project is now and the forward phases — a slim planning doc that points at the detailed forward record rather than duplicating it.
---

# Roadmap

The living planning doc: where CompNeuroVis is *now*, the principles that govern
change, and the forward phases. It stays deliberately thin — the detailed forward
record lives in [Design Directions](design-directions.md) and the
[Widget Authoring Architecture](widget-authoring-architecture.md); the "why" behind
settled choices lives in [Design Decisions](decisions.md); deferred one-offs live in
[Backlog](backlog.md). This doc *sequences* that work, it does not re-describe it.

**Last reconciled with code: 2026-07-11.**

## Current position

The refactor spine has **landed**. The project is built around a single immutable
`AppSpec` (four catalogs), a symmetric actor model where backends and frontends are
the same kind of peer, a generic message bus with explicit routing, and an inline
authoring layer (`cnv.source` / `cnv.neuron.source`, `cnv.layout`, `cnv.show`) that
lowers into the *same* `AppSpec` as a real backend. Live plotting from NEURON and
Jaxley works end to end through the VisPy/PyQt frontend, in scripts and notebooks.
Interactions are ctx-first callbacks; data moves as `ValueChange` / `FieldAppend` /
`FieldReplace`; history is `ON_DEMAND` by default.

What is expressible but **not yet runnable**: the multi-actor, multi-machine
topology. Only in-process and pipe transports exist, the wire protocol still carries
live Python objects, and cross-source composition/remote lowering is stubbed.

The immediate work is **alpha hardening**, not new architecture: the docs / tests /
skills / scratch are stale relative to the refactored code, and a set of boundary
smells remain (see [Design Directions §7](design-directions.md)).

## Governing principles

Stable direction; changed only by deliberate discussion.

- `Field` / `FieldSpec` is the primary data primitive; `AppSpec` (+ optional
  backend) + frontend + transport is the top-level split.
- Treat the core model and message protocol as an internal runtime substrate, not
  the default scientific authoring surface. The inline layer is the surface.
- Keep NEURON, Jaxley, MOOSE, and other simulator users in their native programming
  model: attach to native objects/refs/callbacks via `cnv.neuron.source(...)`;
  observe, expose controls, add views — do not replace simulator code with a
  framework-owned DSL or model base class.
- Frontend state is owned by the frontend, not the backend.
- Prefer typed append/patch messages over bundled full-state replacements when only
  part of the state changed.
- Keep backend choice, feature choice, and layout choice orthogonal.
- The frontend is a swappable implementation of a message protocol; VisPy is one
  implementation (see [Widget Authoring Architecture §7](widget-authoring-architecture.md)).
- Composition is peer actors on the bus, not a wrapping backend; the app spec is the
  integrator's merge of fragments.
- Treat physics engines as backend-side adapters when they participate in simulation
  state; Unity is a frontend when it renders, a backend adapter when it runs physics.

## Forward phases

Each phase points at where its detail lives. Rough order of leverage.

### Phase A — Alpha hardening (current)

Bring the harness back in line with the refactored code and close the boundary
smells, so the rest of the work happens on solid ground.

- Docs / tests / skills / scratch cleanup (see the alpha cleanup review and
  [Design Directions §9](design-directions.md) for the harness strategy).
- Make the examples the executable golden anchor; promote the golden harness into
  `tests/`.
- Boundary-smell sweep: stray `print`s in hot paths, session singleton,
  `ValueOrBinding = Any`, `RenderedFrame` as a separate output stream, the notebook
  render-process env fork ([Design Directions §7](design-directions.md)).

### Phase B — Authoring layer — implemented

The open widget, panel-host, control, operator, selection, and visual-contribution
paths have landed. The active follow-through is physical component and
infrastructure organization.

- Current record and remaining organization sequence:
  [Widget Authoring Architecture](widget-authoring-architecture.md).
- Longer-term `Feature` bundles remain in
  [Design Directions §6](design-directions.md).

### Phase C — Interaction and layout ergonomics

- Selection-as-a-binding-value; declarative cross-panel linking
  ([Design Directions §2](design-directions.md)).
- Layout workbench: grid → recursive split-tree, per-child sizing, `PanelSpec`
  camera-field cleanup ([Design Directions §4](design-directions.md)).

### Phase D — Distribution and alternate frontends

- Serializable wire protocol (spec envelope + typed array payloads) — the gate for
  everything else here ([Design Directions §3](design-directions.md)).
- Network (WebSocket) transport; composition and remote lowering via the fragment
  integrator; `cnv.serve` / `cnv.remote` cross-seam authoring.
- Frontend as a stated, swappable protocol; `cnv.show(frontend=…)`
  ([Widget Authoring Architecture §7](widget-authoring-architecture.md)).
- The target is that every row of the [App Configuration Matrix](app_configuration_matrix.md)
  becomes runnable, not just expressible.

### Phase E — Performance (ongoing)

Per-field `sample_dt` generalization, priority command lane, frontend ring buffers,
visibility-aware refresh, spatial latest-state fast paths, line-plot draw reduction,
and the canvas/backend investigation ([Design Directions §5](design-directions.md)).

## Benchmark apps

Validate architectural changes against these. If a change improves abstractions but
degrades these workflows, it is incomplete.

- **signaling-cascade** — scientific plotting + controls + live updates, morphology
  not the main story.
- **external pharynx research workflow** — custom interactions, multi-trace
  selection, mode-like workflows, real authoring pressure. A separate research
  codebase; referenced only as a high-level benchmark.
- **complex NEURON morphology** — heavy live morphology rendering, update cadence,
  click-to-trace under load.
- **Jaxley multicell** — the same ideas working outside the NEURON backend.
- **surface cross-section / animated surface** — display/history separation, surface
  invalidation, replay-style thinking outside morphology.

## Open questions

- What is the stable public surface for app modes (live / static-replay / editor /
  headless) over the shared substrate?
- Where does a reusable `Tool` abstraction sit so simulator, editor, and frontend
  interaction tools share structure without one ontology?
- First co-simulation timing policy for neural-plus-body workflows: lockstep,
  substeps, or async latest-state exchange?
- First notebook milestone: notebook-native frontend, sidecar desktop window, or both?

## Update rule

- New forward direction or open architectural question → [Design Directions](design-directions.md).
- Multi-step feature plan → a doc under `proposals/`, linked from here and [Backlog](backlog.md).
- Phase/priority shift → this file.
- Elevated, settled lesson → [Design Decisions](decisions.md) (deliberate review).
- Deferred one-off idea → [Backlog](backlog.md).
