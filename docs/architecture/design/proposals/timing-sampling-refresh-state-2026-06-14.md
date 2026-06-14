# Timing, Sampling, and Refresh State

**Date:** 2026-06-14

This note records the current timing, sampling, data passing, and refresh model
for live CompNeuroVis sources. The immediate performance target is the
C. elegans pharynx viewer, but most of the model is source-agnostic and should
apply to NEURON, Jaxley, replay, synthetic Python sources, and future providers.

## Current Pharynx Settings

The pharynx viewer now separates numerical integration, backend data batching,
and frontend repaint cadence:

```python
SIM_DT_MS = 0.1
DISPLAY_DT_MS = 1.0
MORPHOLOGY_MAX_REFRESH_HZ = 4.0
LINE_PLOT_MAX_REFRESH_HZ = 12.0
```

These values mean:

- the simulator integrates with `dt = 0.1 ms`
- the source/backend emits one display/update batch about every `1.0 ms` of
  simulation time
- each emitted trace append normally carries about ten solver samples
- line plots are eligible to repaint at up to `12 Hz`
- morphology is eligible to repaint at up to `4 Hz`

This is intentionally not one global frame rate. Solver accuracy, update
transport volume, and render smoothness are separate concerns.

## Generic Timing Model

Live visualization has several different clocks:

| Clock | Owner | Role |
|---|---|---|
| Solver/simulation `dt` | Source/provider | Numerical or model progression step. Must preserve model accuracy. |
| Sampling cadence | Source/provider | How often values are sampled from the provider. May differ by field. |
| Emission/display cadence | Source/backend actor | How often sampled values are batched and emitted to the app. |
| Transport cadence/backpressure | Runtime/transport | How updates move between actors and how queues are bounded/coalesced. |
| View `max_refresh_hz` | View spec/frontend | Per-view repaint ceiling. Controls CPU/GUI rendering load. |
| UI event-loop cadence | Frontend host | Polling and interaction cadence. Must leave room for input. |

The architectural rule is that these clocks should stay decoupled.

Changing update batching should not change solver accuracy. Lowering morphology
refresh should not reduce trace sampling fidelity. Raising line refresh should
not force morphology to repaint at the same rate. Slower rendering should not
block controls or clicks.

## Generic Data Semantics

Fields should be updated according to their semantics, not according to a single
default app cadence.

### Latest-state fields

Latest-state fields represent the current provider state. Examples:

- morphology color
- current surface scalar values
- current state markers
- control-derived display state

These should usually be sent as `FieldReplace`. If the frontend falls behind,
older values can often be dropped or coalesced because only the newest state is
visible.

### Historical fields

Historical fields represent a time series. Examples:

- selected voltage traces
- gating/state variables
- currents
- replayed time series

These should be sent as `FieldAppend` with a clear append dimension and a
bounded retention policy. Full-history collection should be explicit because it
changes both memory and transport cost.

### Derived and selected fields

Many interactive views need only a selected subset of the provider state. These
should not require full-source history. A selected trace can be sampled and
emitted as selected rows only, while a morphology or surface view continues to
receive latest-state updates.

## History Mode

History mode is the mechanism that decides whether the app captures all entity
history or only selected/on-demand traces.

### On-demand history

In on-demand mode:

- latest-state fields remain latest-only
- selected traces sample only selected entities
- emitted history fields contain only selected rows
- full source-by-time matrices are avoided

This is the right default for interactive visualization because users usually
inspect a small active subset while using latest-state views for spatial context.

### Full history

In full history mode:

- all relevant entities are sampled over time
- emitted history fields may contain full entity-by-time matrices
- memory and transport costs are intentionally higher

This is correct for replay, retrospective selection, analysis, and any workflow
that requires all-entity time history.

The important point is that full history is a capability, not the default shape
for every live app.

## Current NEURON Attach Implementation

The current NEURON attach path is the concrete implementation that motivated
this note.

### Current pharynx update shape

In the pharynx viewer, one backend tick currently emits:

```text
segment_display:   (8,)       latest morphology values only
segment_history:   (1, 10)    selected trace samples only
exp2_state_trace:  (5, 10)    EXP-2 ref samples
currents_trace:    (1, 10)    current ref samples
```

This is the correct shape for on-demand history:

- morphology is a present-state spatial view
- selected voltage history is only the selected trace
- EXP-2 state and current traces are explicit historical line fields

### NEURON-specific fast paths

NEURON attach uses provider-specific primitives where they matter:

- selected voltage traces are sampled through a small selected-segment
  `h.PtrVector`
- high-frequency mechanism refs are declared with `sim.line_refs(...)`
- `line_refs(...)` samples NEURON `_ref_*` handles with `h.PtrVector.gather()`
- full segment-by-time sampling is reserved for `HistoryCaptureMode.FULL`

This belongs inside `cnv.neuron.attach(...)` because attach is the source API for
the NEURON provider. It can stay inline while still understanding NEURON
sampling primitives.

Generic `sim.line(record=...)` remains useful for non-NEURON Python callables,
but it is not the right path for high-frequency NEURON mechanism state.

## Refresh Scheduling

Frontend refresh has two layers:

- per-view `max_refresh_hz` determines whether a dirty view is due
- the UI host soft deadline prevents too much repaint work from running in one
  event-loop turn

The soft deadline is not the main performance mechanism. It is a latency guard:
if a repaint is unexpectedly expensive, remaining dirty work stays queued for a
later UI turn instead of starving mouse, keyboard, and control events.

The main performance mechanism is avoiding unnecessary work:

- sample less data when history mode allows it
- batch samples before transport
- coalesce latest-state updates
- repaint each view only at its own requested cadence
- avoid refreshing spatial views at line-plot cadence

## Why The Current Approach Is Correct

The current approach follows the app architecture:

- a source exposes provider-specific capabilities
- fields are the data contract
- views consume fields but do not own simulation timing
- history mode controls data retention shape
- transport moves updates; it should not define app semantics
- frontends own repaint cadence and event-loop fairness
- provider-specific optimizations stay inside provider attach/source code

This separation fixes two recurring problems:

- frontend starvation from continuously dirty heavy views
- backend waste from treating latest-state morphology as if it were full trace
  history

## Remaining Improvements

These are useful optimizations before doing line-panel downsampling.

### Per-field or per-line `sample_dt`

Sampling cadence should be expressible per field or per line source:

```python
sim.line_refs(..., sample_dt=0.5)
```

This preserves solver accuracy while reducing visual trace append volume. The
same idea applies beyond NEURON: any provider should be able to expose a field
that samples less frequently than the solver/model step.

### Producer-side coalescing

Before sending updates over a transport, producers can coalesce queued visual
updates:

- keep only the latest `FieldReplace` per field
- merge adjacent compatible `FieldAppend` updates per field
- bound visual queue growth when the frontend is behind

This reduces transport traffic and prevents stale visual updates from delaying
current state.

### Priority command path

Clicks, keys, and control changes should not wait behind large field updates.
A dedicated priority lane or command-first poll/drain policy would improve
interaction latency under heavy visualization load.

This does not make rendering cheaper, but it keeps the app responsive when
rendering or transport is busy.

### Frontend ring buffers

Rolling-window line fields currently pay append/copy costs in the frontend
projection. A ring buffer representation for live rolling fields would reduce
allocation and copying.

This is generic and should benefit any source that emits live time-series
fields.

### Visibility-aware refresh

Hidden, collapsed, minimized, or tiny panels should keep their field state
current but skip expensive visual refresh. This is especially useful once panel
layout becomes more dynamic.

### Better refresh grouping

The frontend can become more deliberate about grouping:

- prefer controls and input feedback first
- schedule expensive spatial views separately from line plots
- avoid refreshing multiple heavy panels in the same UI turn when there is no
  user-visible benefit

### Spatial latest-state fast paths

When geometry and style are unchanged, spatial views should update only the
latest scalar/color payload and colorbar state. Mesh rebuild or scene-level work
should be reserved for structural or style changes.

This applies to morphology, surfaces, and any future spatial renderer.

## Eventually: Line Rendering Work Reduction

If line refresh itself remains the dominant cost, line panels need to draw less
work per repaint:

- downsample to visible pixel columns
- incrementally append to plotted curves when axis/window state permits
- avoid recomputing unchanged series metadata

Those are render-cost reductions. The optimizations above reduce sampling,
transport, and scheduling pressure first, so line-panel work starts from the
right dataflow shape.
