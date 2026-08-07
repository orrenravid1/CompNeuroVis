---
title: Design Decisions
summary: Settled architectural decisions and the lessons that motivated them. Changed rarely and deliberately.
---

# Design Decisions

Settled architectural choices and the evidence behind them. This document changes
rarely and deliberately — new insights start as notes in [Roadmap](roadmap.md) or
[Backlog](backlog.md) and are elevated here after review. Forward-looking open
directions live in [Design Directions](design-directions.md).

**Last reconciled with code: 2026-07-11.** Each decision carries a **Status** line:
*Landed* (in code), *Direction* (agreed, not fully realized), or *Superseded*
(the mechanism changed; the underlying lesson is retained).

---

## Cross-Platform Launch Behavior

**Decision:**
- User-facing launch code should work the same on Windows, Linux, and macOS.
- `cnv.show()` / `run_app(...)` must protect against spawned child re-imports
  internally, so a plain script works without ceremony.
- `if __name__ == "__main__":` is allowed in user scripts but must not be
  *required* by the library just to make examples run.
- Model/source construction should be lazy for worker-backed apps. The recommended
  pattern hands the library a source (or a zero-arg build callable), not an
  already-launched runtime.
- Frontend-only interaction state is a separate concern from backend construction.
  The canonical architecture must not rely on instantiating a second full backend
  in the UI process to recover custom interactions.

**Why:**
Worker-side error routing only helps code that runs inside the worker. Eager
construction at module scope runs side effects and exceptions before that
handling exists. On Windows, multiprocessing spawn re-imports `__main__`, so heavy
top-level work runs multiple times unless guarded — the library should absorb that,
not push it onto the author. Semantic interaction (`InvokeAction`, `KeyPressed`,
`EntityClicked`) handled backend-side with emitted `ValueChange` / `Status`
responses is the chosen model, rather than a second UI-process backend.

**Status:** Landed. Inline `cnv.show()` lowers a source through the same
`RunSpec` / `run_actor` path used by every actor; the spawn-guard concern is real
and handled in the launch layer.

---

## Frontend Invalidation

**Decision:**
- Whole-window refreshes are too coarse for performance-sensitive scenes.
- The frontend invalidates only the affected targets.
- Protocol and updates follow the same rule: send only what the affected targets
  need, not broad bundled refreshes by default.
- Broader updates are opt-in — a producer that wants them asks explicitly.
- Current explicit targets: controls, morphology, surface visual, surface axes,
  surface slice overlay, per-view line plots, and per-view state graphs.

**Why:**
Real-scene profiling showed a slice change should update only the derived line plot
and slice overlay — not the surface mesh, axes, or unrelated panels. Long-lived
visuals and renderer-side caches are required for good performance; rebuilding them
on every change was the original bottleneck.

**Status:** Landed. `RefreshPlanner` / `RefreshTarget` route value and field
changes to exactly those targets (`controls`, `morphology`, `line_plot`,
`surface_visual`, `surface_axes`, `state_graph`).

---

## Protocol Granularity and History Separation

**Decision:**
- High-throughput rendering defaults to need-to-know updates.
- `FieldAppend` is the normal path when it correctly expresses the change;
  `FieldReplace` remains valid but is the explicit broader-cost path.
- Latest-state display and captured history are different concerns and must not be
  forced into the same default storage/update path.
- `HistoryCaptureMode`: `ON_DEMAND` by default; `FULL` as an explicit opt-in for
  all-entity history capture.
- Display roles are field-generic, not voltage-specific. Low-level compartment
  producers may use role-based conventions (`segment_display`,
  `segment_history`); source-authored widgets may allocate unique fields. Neither
  form claims that the displayed quantity is inherently voltage.

**Why:**
Live backends must not resend full trace history on every update. Incremental live
data belongs in typed append updates, with the frontend owning displayed rolling
history. Full history for every entity is valuable for click-later inspection and
replay, but should be configurable rather than imposed on every live app.

**Status:** Landed. `FieldAppend`/`FieldReplace` are the update primitives,
`HistoryCaptureMode.ON_DEMAND`/`FULL` exist, and low-level role fields coexist
with unique source-widget fields. (Separating simulation cadence from presentation
cadence — a related but distinct concern — remains partly open; see
[Design Directions §5](design-directions.md).)

---

## Architectural Automation

**Decision:**
- Important vocabulary and protocol-taxonomy decisions must not live only in prose.
- When the repo retires or canonizes a term, encode the smallest useful
  machine-readable check in the normal test suite.
- Prefer immediate convergence plus automated detection of stale names over
  compatibility aliases that let drift persist unnoticed. For deliberate taxonomy
  changes: remove the old term, ban it on active surfaces, update derived docs, let
  checks surface any missed sites.

**Why:**
Compatibility aliases hide incomplete migrations by keeping tests green while docs,
skills, and generated references go semantically stale. Automated enforcement is
the only reliable fix once the codebase outgrows manual review.

**Status:** Landed narrowly in `tests/test_repository_hygiene.py`. It checks retired
widget-taxonomy names, documented example paths, and published-doc navigation.
This is intentionally ordinary test code rather than a second policy framework;
coverage must grow only when a concrete drift class justifies it.

---

## Explicit Frontend Host/Panel Naming

**Decision:**
- When a visible region has both a host widget and an inner rendering/control
  widget, public seams name both layers explicitly.
- Avoid ambiguous singular handles once multiple panels or wrapper hosts exist;
  prefer plural collections plus explicit lookup, e.g. `line_plot_host_panels`,
  `line_plot_panels`, and `line_plot_panel(view_id)`.

**Why:**
Once line plots and controls adopted the same framed host-wrapper pattern as 3-D
views, singular names stopped saying whether callers meant the visible chrome or
the inner widget. Explicit host/panel naming keeps multi-panel layouts reasoning-
friendly.

**Status:** Landed. The frontend holds `line_plot_host_panels` / `line_plot_panels`
(and the parallel morphology/state-graph collections).

---

## Generic Layout System

**Decision:**
- Layout is fully generic and composable, with one default arrangement rather than
  hard-coded app categories.
- The user-facing model should feel like Blender/Unity/Unreal: a default layout
  that works immediately, customizable when needed, no assumption that a 3-D
  viewport is always primary.
- Multi-series line plots are first-class, not an edge case.
- 3-D hosting is a swappable layout concern: `ViewSpec` describes *what* to render;
  a separate host layer describes whether views use independent canvases, shared
  canvases, or other strategies.

**Why:**
A narrowly simplified abstraction is still wrong if it is not composable. A user who
starts with "plot a few live traces and expose sliders" must be able to add
morphology or a surface later without changing mental models.

**Status:** Direction. The composable core is in place and `cnv.layout(...)` places
panels by handle, but the topology is still a flat grid. The recursive split-tree
"workbench" and the `PanelSpec` camera-field cleanup are tracked in
[Design Directions §4](design-directions.md).

---

## Startup Layout Behavior

**Decision:**
- A live app must not visibly start in a fallback layout and then jump to the
  intended one when the initial structure is already knowable.
- If layout and views are known before launch, the app declares them up front so
  the window opens directly into the intended arrangement.

**Why:**
Visible startup jumps signal that layout knowledge is fragmented across the
construction path and make a poor first impression.

**Status:** Superseded mechanism, lesson retained. The old `@classmethod
startup_scene(cls) -> Scene` hook is gone. The same guarantee now comes from a
source declaring its panels/views and `cnv.layout(...)` up front, launched via
`cnv.show()` — the layout is known before the backend starts, so there is no
loading-only phase to jump out of.

---

## Public Interaction API

**Decision:**
- The internal architecture may use tools/controllers, but the default user-facing
  API must not require users to think in those terms.
- Custom interactions should be expressible with a few small callbacks and strong
  defaults.
- The framework exposes semantic interaction hooks: action/button invocation, key
  press, clicked entity.
- For worker-backed apps these hooks run backend-side, driven by semantic commands,
  not frontend-only callback objects.
- Per-app interaction policy stays outside core renderer/transport logic.

**Why:**
Profiling real authoring (pharynx, signaling cascade) showed that if a user has to
ask "does this method go in the frontend object or the backend or it breaks pipes?",
the authoring model has failed. The audience is closer to SciPy/matplotlib/NEURON/
Plotly users than engine authors.

**Status:** Landed. Interactions are ctx-first callbacks (`entity_click(ctx, id)`,
`key_press(ctx, key)`, action `fn(ctx)`) registered via `src.interactions(...)` /
`src.action(...)`; per-app logic lives in the source, not split across frontend and
backend classes.

---

## Public Authoring Surface

**Decision:**
- The simplified public API must stay feature-composable.
- High-level helpers assemble the same underlying `AppSpec` + actor + transport
  model rather than introducing separate app families.
- Backend choice, feature choice, and layout choice stay orthogonal. A NEURON-backed
  app with controls and traces but no morphology is a valid first-class shape.
- Preferred UX: declare controls, declare exposed series/fields, declare
  views/layout, opt into built-ins (reset, pause/play), provide model lifecycle
  hooks — the library owns spec assembly, history buffering, and protocol packaging.
- Adding morphology, surfaces, or extra plots to an existing app means adding
  declarations, not rewriting around a different abstraction.

**Why:**
A narrowly simplified abstraction is still wrong if it is not composable. Backend-
labeled helpers become misleading if they imply a default visualization mode —
naming a backend must not imply morphology is always shown.

**Status:** Largely landed. The inline source layer realizes this: `cnv.source` /
`cnv.neuron.source` with `.morphology / .line / .bar / .control / .action`, backend
choice orthogonal to features, no forced morphology. The old `build_*_app(...)`
backend-labeled builders are gone. The remaining piece — reusable `Feature` bundles
that contribute controls/traces/tools/views declaratively — is
[Design Directions §6](design-directions.md).

---

## Technical: NumPy Masked Divide

`np.divide(..., where=...)` without `out=...` can leave masked entries undefined and
emit warnings. Geometry normalization paths use explicit output buffers.

**Status:** Landed. The geometry orientation path uses `np.divide(ax, ax_n,
out=ax_u, where=...)`.
