---
title: Adaptive Presentation Scheduler
summary: Proposal for app-wide, cost-aware refresh admission that balances responsiveness, continuity, fairness, and frame-time constraints without changing data semantics.
status: proposal
date: 2026-08-06
---

# Adaptive Presentation Scheduler

## 1. Decision sought

Replace independent fixed-rate panel refresh decisions with one frontend-local
presentation scheduler. The scheduler should choose which dirty panels to present
on each UI turn by balancing semantic presentation needs against measured refresh
and paint cost, the available frame-time budget, interaction latency, visibility,
and fairness.

The target is:

> Maximize useful, timely visual presentation for the app as a whole within the
> frontend's measured resource budget, without changing simulation, sampling,
> retention, transport, or projection semantics.

This is not a request for a widget-specific line-plot throttle. A fixed rate can be
a useful baseline or explicit ceiling, but it cannot optimize an app containing
several lines, a morphology, an animated surface, controls, and third-party panels
whose costs change with data size and user interaction.

## 2. Current state and motivating evidence

CompNeuroVis already separates several clocks that must remain independent:

- solver integration `dt`;
- data sampling cadence;
- producer emission and batching cadence;
- transport polling and message draining;
- frontend projection updates;
- visual presentation and eventual paint cadence.

The desktop frontend also already has much of the required substrate:

- a nominal 60 Hz Qt timer;
- a soft per-turn frontend budget;
- bounded inbound draining and update compaction;
- precise refresh targets;
- long-lived panel lifecycles and renderers;
- pending-work queues;
- per-view `max_refresh_hz` values;
- structured performance logging and selected paint-time measurements.

What is missing is global admission. Today a panel lifecycle decides whether it is
due, and `PanelManager` visits pending lifecycles in least-recently-served order
until the turn's deadline. That kind-neutral ordering prevents the layout's first
expensive host from starving its peers, but the cost and benefit of one refresh
are not compared with the other pending work in the app.

The line behavior comparison that prompted this proposal exposes the limitation:

- `main` gives lines a fixed 15 Hz default and limits line work per flush;
- the widget-authoring branch currently gives Line an explicit non-positive cap,
  which opts out of lifecycle throttling and can attempt both lines in
  `complete_interface.py` on every frontend turn;
- the producer, field-append, rolling-window, and PyQtGraph data paths are otherwise
  substantially the same.

More requested frames can therefore produce less regular visible motion: two
independent approximately 60 Hz loops expose phase jitter, `setData()` and
`setXRange()` consume more CPU, and Qt may coalesce paints after work has already
been prepared. A stable 15 Hz baseline may look smoother, but hard-coding 15 Hz is
not the general solution.

## 3. Goals

1. Optimize the visible app, rather than each widget in isolation.
2. Keep controls, selections, and direct manipulation responsive under render load.
3. Give continuous displays regular frame pacing, not merely the highest possible
   average refresh count.
4. Degrade expensive or latest-state displays gracefully when the app is
   overloaded.
5. Bound visual queue growth and avoid preparing frames that cannot be painted.
6. Prevent starvation across panels and contributions.
7. Learn real costs at runtime; do not require widget authors to predict them.
8. Give built-in, app-local, and installed third-party panels the same contract.
9. Preserve every row of the App Configuration Matrix: each frontend schedules
   locally according to its own device, transport, visibility, and interaction
   role.
10. Make decisions observable and reproducible through structured telemetry and
    deterministic scheduler tests.

## 4. Non-goals

- Changing solver accuracy or slowing simulation to make a frontend appear smooth.
- Dropping historical samples that are valid under field-retention policy.
- Moving frontend performance policy into NEURON, Jaxley, or inline producers.
- Baking knowledge of `line_plot`, `surface`, `morphology`, or any third-party kind
  into the scheduler.
- Running an expensive exact optimizer on every UI turn.
- Promising identical frame rates across Qt, notebooks, Web, Unity, and headless
  frontends.
- Treating a rendered frame as scientific data persistence.

## 5. Invariants

### 5.1 Data correctness precedes presentation

Every accepted `FieldAppend`, `FieldReplace`, value update, patch, and selection
update is first applied to `AppProjection`. Presentation work may coalesce to the
latest projected state, but the scheduler does not rewrite field history.

### 5.2 Sampling is not rendering

Sampling cadence, retention, and producer batching remain producer/data contracts.
Presentation policy cannot silently change them. Conversely, a high sampling rate
does not obligate a frontend to paint every sample.

### 5.3 Invalidations are semantic; admission is local

`RefreshPlanner` continues to say what became stale. It does not decide when it is
painted. The presentation scheduler consumes neutral dirty work and local runtime
facts to decide admission.

### 5.4 Widget kinds are not scheduling classes

Presentation needs are expressed through generic policy. Two instances of the
same widget may receive different service because one is visible, interacting,
larger, more expensive, or more stale. Different widget kinds may receive the same
service when their needs and costs are equivalent.

### 5.5 One panel presentation is transactional

The normal scheduling unit is a mounted panel lifecycle. A host may merge multiple
view or contribution invalidations into one transaction and commit its shared
canvas once. The scheduler must not force Scene3D layers or Plot2D additions to
perform redundant commits merely because they originated as separate targets.

### 5.6 Frontend autonomy

Portable authored intent may cross the canonical boundary. Runtime cost estimates,
paint acknowledgements, visibility, interaction boosts, device load, and admission
history remain frontend-local.

## 6. Presentation intent

The existing `max_refresh_hz` is only one constraint. The eventual canonical,
data-only vocabulary should be able to express a small `PresentationPolicySpec`
or an equivalent immutable property set:

```python
PresentationPolicySpec(
    mode="latest",             # latest | continuous | responsive
    target_hz=None,            # soft cadence target
    max_hz=None,               # optional hard ceiling
    max_staleness_ms=None,     # soft service deadline / fairness bound
    weight=1.0,                # relative utility under contention
)
```

The names and defaults remain subject to implementation evidence, but their
semantics are distinct:

- `latest`: intermediate visual states are disposable; presenting the newest
  projection is valuable.
- `continuous`: regular spacing is valuable. Utility rises when the next target
  presentation time is missed, and excessive jitter is penalized.
- `responsive`: changes caused by controls, selection, or direct manipulation seek
  low latency. This does not mean the scheduler must paint every intermediate drag
  event.
- `target_hz`: a soft benefit curve, not a promise and not a producer clock.
- `max_hz`: a hard author/user ceiling. A non-positive legacy
  `max_refresh_hz` maps to uncapped presentation during migration, not to a target.
- `max_staleness_ms`: the point at which fairness urgency becomes dominant.
- `weight`: relative importance only when work competes; it never grants a widget
  correctness privileges.

Authors should normally receive sensible policy presets from a component. They
should not need to estimate milliseconds or know the frontend frame budget. User
overrides remain possible for advanced applications.

Do not add this canonical type before Phase 0 telemetry establishes which fields
are necessary. The first scheduler can adapt the current `max_refresh_hz` into an
internal policy while preserving wire compatibility.

## 7. Runtime candidate model

Each dirty mounted panel contributes a frontend-local candidate containing facts
such as:

```text
presentation id
pending refresh targets
first and most recent invalidation time
last admitted and last actually painted time
portable presentation policy
visibility and effective pixel area
interaction state
estimated preparation, commit, and paint cost
whether an earlier paint is still outstanding
fairness credit / recent service history
```

The panel lifecycle owns how its pending targets are merged and rendered. The
scheduler owns timing and admission. The current lifecycle method that combines
both concerns, `flush_refreshes(...)`, should evolve toward a boundary equivalent
to:

```python
candidate = lifecycle.presentation_candidate(now)
outcome = lifecycle.present(candidate, deadline_s=...)
```

`PresentationOutcome` should report which invalidations were consumed, measured
CPU preparation/commit duration, whether a native paint is expected, and a token
that can be matched to paint completion when the host supports it.

A compatibility adapter may initially wrap existing third-party lifecycles, but it
must be explicitly transitional and removed before 1.0 rather than becoming a
second permanent scheduling path.

## 8. Scheduling formulation

For pending candidates `i` on frontend turn `t`, choose admission variables
`x_i in {0, 1}` to approximately maximize:

```text
sum(x_i * utility_i(t))
```

subject to:

```text
sum(x_i * estimated_cost_i(t)) <= available_budget(t)
hard per-candidate caps
paint-in-flight constraints
host atomicity constraints
```

Utility is a function of:

- age since first invalidation;
- time since the last actual presentation;
- distance from the desired continuous cadence;
- interaction and focus boost;
- maximum-staleness pressure;
- accumulated fairness credit;
- visibility and useful pixel area;
- whether a newer projection superseded the pending one.

An online greedy admission pass is appropriate: order candidates by mandatory
deadline class, then by a stable utility-to-cost score with fairness credit and
hysteresis. Exact knapsack optimization would add cost and instability without
knowing future arrivals or GPU/desktop-compositor latency.

### 8.1 Regularity matters

Continuous panels need a target phase, not only a rate cap. A line whose frames
alternate between 5 ms and 45 ms gaps can feel worse than a regular lower-rate
line. The scheduler should track presentation intervals and increase utility near
the next desired presentation time instead of admitting every arrival immediately.

### 8.2 Interaction boost

Pointer manipulation, selection feedback, keyboard actions, and control changes
temporarily raise the relevant panel's utility and may reduce service for passive
views. The boost decays after interaction ends. Commands themselves retain a
priority path and are not delayed behind presentation work.

### 8.3 Cost learning

Maintain bounded exponentially weighted estimates for:

- lifecycle preparation and renderer refresh time;
- canvas commit time;
- paint latency and paint CPU time where observable;
- realized frontend timer gaps after admitting the work.

Use conservative startup estimates and a minimum cost floor so new or apparently
cheap candidates cannot dominate. Separate estimates by presentation identity and
optionally by coarse size bucket; never trust an author-declared cost as authority.

### 8.4 Paint backpressure

Calling `setData()` or committing a canvas is not the same as presenting a frame.
If a previous paint remains outstanding, new invalidations normally merge into one
latest pending transaction. A host-specific paint signal may release the slot.
Hosts without paint feedback fall back to refresh-completion timing and a bounded
in-flight assumption.

### 8.5 Adaptive budget

The scheduler begins with the frontend's configured soft budget and preserves
headroom for event processing. It reduces presentation admission after timer-gap,
paint, or backlog pressure and recovers gradually when turns remain healthy.
Budget adaptation uses hysteresis to avoid oscillation.

### 8.6 Overload behavior

Under sustained overload:

1. Projection state remains current.
2. Intermediate latest-state presentations coalesce.
3. Invisible work is deferred.
4. Continuous targets reduce cadence while preserving regularity.
5. Interaction feedback and overdue fairness candidates win admission.
6. Queues stay bounded to semantic invalidations, not accumulated frames.

The system must expose overload in telemetry; it must not silently slow the solver
or discard valid retained history.

## 9. Visibility and composition

Visibility is a runtime scheduling fact, not a producer concern. Hidden or
collapsed panels normally keep projection state current while deferring visual
work. When a panel becomes visible, one latest-state transaction catches it up.

Shared hosts group work deliberately:

- Scene3D applies due layer and contribution invalidations and performs one canvas
  commit.
- Plot2D applies line/bar data and owner-authored contributions before one paint.
- Controls group changes for their independently placeable controls panel.
- A third-party host declares its own atomic presentation unit through the same
  lifecycle contract.

## 10. Third-party and built-in parity

The scheduler imports no component and branches on no view kind. First-party and
third-party registrations participate identically.

A normal standalone renderer receives the generic standalone lifecycle and therefore
gets scheduling without additional code. A custom panel host exposes the same
candidate/present contract as first-party Scene3D or Controls. Visual contributions
remain owned by their author and are grouped by the target host capability.

The frontend must validate incomplete scheduling implementations precisely. A
plugin that supplies a QWidget renderer should not be required to implement paint
telemetry; it receives a safe fallback. A plugin that supplies a complete custom
panel lifecycle accepts the fuller contract.

## 11. App Configuration Matrix consequences

- Scheduling occurs independently in every frontend actor. A teacher Qt frontend,
  student browser, and observer notebook may present the same canonical updates at
  different rates without changing backend data.
- Interaction role affects runtime boost and command authority, not canonical
  widget identity.
- Remote transport latency becomes an input to staleness and backpressure metrics;
  it does not merge presentation cadence with producer cadence.
- Headless/export frontends may use deterministic throughput or deadline policies
  instead of interactive frame pacing.
- Broadcast and aggregation do not require one global cross-device scheduler.
- Portable presentation intent remains language-neutral and kind-neutral so Unity
  or Web can interpret it independently.

## 12. Telemetry

Emit structured events and per-panel aggregates for:

- invalidations requested, merged, admitted, deferred, and superseded;
- pending age and maximum staleness;
- intended versus realized cadence and interval jitter;
- preparation, commit, paint, and end-to-end presentation latency;
- outstanding paint count;
- budget offered, consumed, and overrun;
- interaction boost and visibility state;
- fairness credit and starvation prevention;
- inbound backlog and frontend timer gaps around admission decisions.

Telemetry must use stable presentation ids and fragment-scoped view/panel refs. It
must be possible to record a scheduler trace and replay the admission decisions in
a deterministic unit test without launching Qt.

## 13. Migration plan

### Phase 0: measurement baseline

- Add actual-presentation telemetry to Line, Scene3D, Surface, Controls, and the
  app-local gauge where practical.
- Record fixed-duration traces for the benchmark apps.
- Establish `main` and current-branch cadence/cost baselines before changing
  policy.

### Phase 1: one scheduling seam, fixed behavior

- Introduce a `PresentationScheduler` owned by the frontend/PanelManager boundary.
- Route every mounted lifecycle through it while reproducing current fixed policy.
- Keep projection mutation and refresh planning unchanged.
- Add deterministic candidate ordering, cap, visibility, and starvation tests.

### Phase 2: generic fairness and bounded work

- Replace per-widget flush quotas with generic budget admission and fairness.
- Bound outstanding presentation work.
- Ensure custom panel hosts participate through the same seam.

### Phase 3: paint feedback and regular cadence

- Add paint completion signals to the PyQtGraph and Vispy hosts.
- Prevent redundant preparation while a paint is outstanding.
- Add phase-aware continuous scheduling and interval-jitter telemetry.

### Phase 4: adaptive cost-aware admission

- Enable runtime cost estimates, interaction boosts, visibility, and adaptive
  budget control.
- Compare against fixed policies using recorded workloads and GUI checks.

### Phase 5: canonical intent

- Based on evidence, finalize the smallest portable presentation-policy vocabulary.
- Lower it through `ViewSpec` and `VisualContributionSpec` without adding
  widget-kind dispatch.
- Map and then retire the transitional interpretation of `max_refresh_hz`.

### Phase 6: alternate frontends

- Apply the same intent to notebook rendering.
- Ensure future Web, Unity, remote, and headless frontends can choose their own
  scheduler implementation.

## 14. Benchmark and acceptance gates

Use at least:

- `examples/neuron/complete_interface.py`: two scrolling lines, morphology,
  controls, selection, and changing titles;
- `examples/surface_plot/animated_surface_cross_section.py`: animated surface,
  contribution overlay, linked line, and controls;
- `examples/extensions/cnv_pointcloud_demo/demo.py`: third-party Scene3D,
  operator, contribution, Scatter2D, and scoped picking;
- `examples/extensions/local_gauge/demo.py`: custom third-party panel lifecycle;
- a synthetic overload fixture with configurable cheap and expensive panels.

Acceptance requires:

- projection and retained data equal the unscheduled reference after the same
  message sequence;
- no unbounded frame/presentation queue;
- no visible dirty panel exceeds its policy's starvation bound under feasible
  load;
- direct interaction remains within its declared latency objective under feasible
  load;
- continuous panels have lower interval jitter than an unthrottled arrival-driven
  baseline at equal or lower frontend cost;
- expensive latest-state panels reduce cadence before controls or interaction
  feedback become unresponsive;
- two instances, two fragments, and third-party hosts receive independent fair
  service;
- the scheduler contains no built-in widget kind names;
- all automated release gates pass, followed by the documented manual GUI runs.

## 15. Open questions to resolve with evidence

1. Which hosts can provide reliable actual-paint acknowledgement on every supported
   Qt/Vispy configuration?
2. Should `max_staleness_ms` be canonical authored intent or a frontend/user-profile
   default?
3. Is relative `weight` useful to ordinary authors, or should it remain an internal
   expansion of semantic presets?
4. Should a panel that is visible but below a pixel-area threshold be treated as
   hidden, heavily downweighted, or rendered at reduced quality?
5. How should an export frontend express deterministic quality when wall-clock
   responsiveness is irrelevant?
6. What trace duration and percentile thresholds make GUI performance regressions
   reliable enough for release gating?

These questions do not block Phase 0. They are reasons to measure before freezing
the canonical policy vocabulary.
