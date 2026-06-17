---
title: Canvas Backend and Rendering State
summary: Current notes on VisPy/Qt canvas performance, swap interval behavior, backend-path options, and remaining rendering work.
---

# Canvas Backend and Rendering State

**Date:** 2026-06-17

This note records the current state of the VisPy canvas/backend-path
investigation. It is paired with
[Timing, Sampling, and Refresh State](timing-sampling-refresh-state-2026-06-14.md):
that note covers solver cadence, sampling, update batching, history mode, and
view refresh caps; this note focuses on what happens after the frontend decides
a 3-D view or line plot is due to repaint.

No new GUI experiment is required to interpret this state. The goal is to keep
track of what has already been observed, which knobs are real architectural
seams, and which future experiments are worth running when there is time.

## Current Rendering Path

The current desktop frontend embeds VisPy in Qt through VisPy's Qt backend. In
practice this means:

- the frontend host runs in the main process and main thread
- Qt owns the event loop
- VisPy's Qt backend provides a native Qt OpenGL widget for the 3-D canvas
- pyqtgraph paints line plots in the same Qt GUI thread
- mouse, keyboard, controls, pyqtgraph paint, and VisPy canvas draw all share
  one event loop

This path is the right default for application composition because it embeds
cleanly into Qt panels and splitters. Its weakness is that any blocking GL draw,
buffer swap, or pyqtgraph paint blocks the same thread that must process input.

## Current Timing Knobs

The frontend has separate scheduling controls:

```python
FRONTEND_TIMER_INTERVAL_MS = 1000 // 60
FRONTEND_STEP_SOFT_BUDGET_S = 0.012
```

The host timer asks Qt to run frontend work at about 60 Hz. The soft budget is
a fairness guard: if polling and update handling already consumed the budget,
due refreshes are deferred instead of adding more work to the same event-loop
turn.

Views then have their own refresh ceilings, such as morphology and line-plot
`max_refresh_hz`. These are intentionally separate from solver `dt` and display
emission `dt`.

The important limitation is that the soft budget cannot preempt work once Qt or
OpenGL has entered a blocking paint/draw call. It can prevent the app from
starting extra refresh work in the same turn, but it cannot make a 31 ms canvas
draw return in 12 ms.

## Current Swap-Interval Requests

The code now requests immediate swaps in three places:

- the VisPy `SceneCanvas` is created with `vsync=False`
- the frontend host sets Qt's default `QSurfaceFormat` swap interval to `0`
  before `QApplication`, window, and canvas construction
- the 3-D viewport requests swap interval `0` on the native canvas format after
  creating the VisPy canvas and before adding it to the layout

These requests are useful and should stay instrumented, but they should not be
treated as proof that vsync is disabled. Qt and the platform are allowed to
ignore or revise swap-interval requests. The observed logs are the authority for
what actually happened in a run.

## Observed Pharynx Runs

The current C. elegans pharynx viewer exposed the recurring freeze class:
rendering cost can saturate the GUI event loop even when dataflow and sampling
are already decoupled.

### Battery / integrated GPU run

Observed renderer:

```text
AMD Radeon(TM) Graphics
```

Relevant observations:

- frontend default surface request: swap interval changed from `1` to `0`
- first GL info log still reported `qt_swap_interval=1`
- `view_3d/canvas_draw` median was about `31 ms`
- line-plot paint clustered at about `16 ms`

This showed that app-level Qt default format configuration alone did not force
the realized canvas to swap immediately.

### Plugged-in / NVIDIA run

Observed renderer:

```text
NVIDIA GeForce RTX 3070 Laptop GPU
```

Relevant observations:

- frontend default surface request again changed from `1` to `0`
- the native canvas swap-interval configuration reported requested
  `swap_interval_after=0`
- first GL info log still reported `qt_swap_interval=1`
- `view_3d/canvas_draw` median remained about `31 ms`
- `view_3d/canvas_draw` p95 reached about `47 ms`
- morphology refresh and commit work were effectively cheap
- line-plot paint again clustered around one vblank-sized interval

This run matters because it removed "laptop unplugged/integrated GPU only" as
the whole explanation. Plugged-in NVIDIA rendering was better in some ways, but
the Qt canvas path still appeared vblank-locked during draw.

## Current Interpretation

The bottleneck is not morphology data preparation.

The key distinction is:

| Stage | Current read |
|---|---|
| Morphology field update | Latest-state scalar update, not full history. Correct shape. |
| Morphology refresh | Cheap in the measured pharynx runs. |
| Viewport commit | Cheap; mostly asks the canvas to update. |
| Canvas draw | Expensive and vblank-shaped. Main 3-D rendering risk. |
| Line plot paint | CPU/Qt/pyqtgraph-bound and also vblank-shaped in logs. |

The architecture has already made the correct high-level split:

- solver accuracy is controlled by solver `dt`
- update emission is controlled by display/batch cadence
- history mode controls whether full traces or selected traces are retained
- latest-state morphology does not store full trace data
- each view has its own refresh ceiling
- the host has a soft budget to avoid starting too much refresh work per UI turn

The remaining issue is lower in the stack: the current embedded Qt canvas and
line-plot painting paths can still block the GUI thread for longer than the
event-loop budget.

## What Is Correctly Decoupled

### Simulation and display cadence

Solver `dt`, display update cadence, and view repaint cadence are separate. That
is the right model. Slowing morphology repaint should not degrade numerical
integration, and reducing trace sampling should not change the simulation.

### Latest-state and history data

Morphology color is a latest-state display field. It should be sent as current
state and coalesced when possible. It should not store a full entity-by-time
matrix unless an explicit full-history workflow asks for it.

Line traces are historical fields. They should use append semantics, bounded
retention, and eventually append-efficient frontend storage.

### Data update and render presentation

Frontend state can receive field updates without immediately repainting every
dirty panel. Dirty views are presented according to their own refresh ceilings
and the host budget.

This is the key reason throttling morphology is correct: it controls repaint
pressure without throwing away the field/state model.

## What Is Still Coupled

### Qt GUI thread coupling

Input handling, control widgets, pyqtgraph paint, and VisPy canvas draw still
share one Qt GUI thread. That is a concrete implementation limit, not a data
model limit.

### Blocking draw cannot be preempted

Once the embedded canvas enters a blocking draw or swap, the host budget cannot
interrupt it. Budgeting helps decide what not to start; it does not split a
single OpenGL paint call into smaller work units.

### Multiple heavy panels can align badly

Even with separate `max_refresh_hz` settings, several due panels can become
eligible in the same frontend turn. The current budget prevents unbounded work,
but future scheduling can be more deliberate about spreading heavy panels across
turns.

## Dedicated Pipes And Priority Lanes

Dedicated pipes or priority lanes are still useful, but they solve a different
problem.

They can improve:

- command latency when update queues are full
- command-first draining under sustained backend traffic
- stale latest-state coalescing before messages reach the frontend
- isolation between high-frequency trace traffic and low-frequency semantic
  commands

They cannot fix:

- a blocking `paintGL`
- a vblank-locked buffer swap
- pyqtgraph spending a full vblank-sized interval in paint
- all input events being delayed while the GUI thread is inside rendering

So the ordering should be:

1. Keep data and command semantics decoupled.
2. Add producer/transport coalescing and priority command handling for latency.
3. Continue reducing render work and render frequency.
4. Treat canvas backend changes as a separate frontend implementation question.

## Canvas Backend Options

### Current: VisPy Qt backend with embedded Qt OpenGL widget

This remains the best integrated default.

Pros:

- embeds cleanly in the existing Qt layout
- works with current panel composition
- shares the normal Qt input and focus model
- keeps one application window

Cons:

- the realized swap interval appears to stay at `1` on the observed Windows
  runs
- the draw path can block the GUI thread
- Qt widget composition may add overhead beyond raw scene rendering
- driver-level vsync policy can override application requests

This path should stay supported, but it needs conservative refresh budgeting.

### Candidate: Qt `QOpenGLWindow` embedded with `createWindowContainer`

This is the most plausible Qt-native alternate path.

Pros:

- avoids some `QOpenGLWidget` composition costs
- is closer to a native OpenGL window surface
- may honor swap behavior differently on Windows
- can still be hosted inside a Qt widget layout through a container

Cons:

- VisPy does not expose this as a simple public backend switch today
- likely needs a custom VisPy/Qt backend path or a lower-level renderer adapter
- embedded native windows can have focus, stacking, clipping, and layout quirks
- it is a real spike, not a one-line substitution

This is the first serious experiment to run when there is time.

### Candidate: VisPy GLFW backend

GLFW is useful as a diagnostic and possibly as a detached high-performance
morphology window.

Pros:

- has its own direct swap-interval call
- may honor `vsync=False` more predictably on some systems
- isolates the 3-D window from Qt widget composition

Cons:

- does not embed cleanly in the current Qt panel system
- introduces a second event-loop/window-management path
- would complicate focus, selection, controls, and app composition

Use this to answer "is the scene itself slow, or is the Qt canvas path slow?"
Do not treat it as the default app architecture unless embedding and input are
solved.

### Candidate: VisPy SDL2 backend

SDL2 is similar to GLFW for this purpose.

Pros:

- useful detached-rendering diagnostic
- has explicit swap-interval control

Cons:

- same integration problem as GLFW
- less aligned with the existing Qt app shell

### Candidate: EGL or OSMesa offscreen rendering

These are not primary interactive desktop canvas paths.

Pros:

- useful for headless rendering, export, snapshots, CI diagnostics, and future
  report/poster pipelines

Cons:

- not a clean interactive embedded Qt panel
- readback/composition into Qt would likely add its own costs
- picking and camera interaction would need separate plumbing

This is valuable for headless/export modes, not for fixing the current live
interactive window.

## Recommended Next Diagnostics

When there is time to experiment, the next measurements should be narrow:

1. Log both `native.format().swapInterval()` and
   `native.context().format().swapInterval()` on first draw.
2. Enable Qt OpenGL/platform logging for one run to see what surface format Qt
   actually realizes.
3. Compare a tiny VisPy scene against the full morphology scene in the same Qt
   backend.
4. Compare current embedded Qt canvas against a minimal `QOpenGLWindow`
   container spike.
5. Compare current embedded Qt canvas against a detached GLFW canvas.

The decision criterion is not just lower draw time. The replacement path must
preserve app composition, input, picking, controls, and predictable lifecycle
behavior.

## Recommended Current Position

Do not redesign dataflow around the canvas problem.

The current sampling, history, update, and refresh model is the right
architecture. It correctly avoids full-history morphology traffic, avoids
tying solver `dt` to visual cadence, and gives each view its own presentation
ceiling.

The right near-term posture is:

- keep morphology as latest-state data
- keep line traces as historical append data
- keep per-view refresh throttles
- keep the frontend soft budget
- keep swap-interval requests and instrumentation
- add priority/coalescing work for command/update latency
- reduce line-plot draw work when line panels remain the dominant cost
- investigate alternate canvas paths only as a focused frontend spike

## Future Optimizations

### Context-level swap instrumentation

The current logs show a mismatch between requested canvas swap interval and
first-draw reported swap interval. Logging the realized `QOpenGLContext` format
will make that mismatch explicit.

### Tiny-scene baseline

A trivial scene should be measured in the same embedded Qt canvas. If the tiny
scene still costs one or two vblank intervals, the backend path is the main
problem. If the tiny scene is cheap, morphology rendering itself needs a deeper
VisPy-side look.

### Alternate Qt canvas spike

A `QOpenGLWindow` container spike is the most relevant alternate path because
it keeps the app in Qt while avoiding the current widget canvas path. This
should be measured before considering a broader renderer rewrite.

### Render scheduling groups

The frontend can schedule heavy panels more deliberately:

- input feedback first
- controls and command processing before optional redraw
- at most one expensive spatial canvas draw per UI turn
- line panels staggered when several are due together

This does not make one draw cheaper, but it reduces event-loop starvation.

### Visibility-aware redraw suppression

Collapsed, hidden, minimized, or very small panels should keep their field state
current but skip expensive visual redraw. This matters more as the layout system
gets more dynamic.

### Line-plot draw reduction

Line plots may need render-cost reductions independent of 3-D canvas work:

- visible-pixel downsampling
- append-efficient rolling buffers
- incremental curve updates when axes and visible window are stable
- grouping/staggering multiple line panels

These are line-rendering optimizations, not fixes for a blocking 3-D swap.

### Headless/export rendering path

Poster workflows will eventually benefit from a noninteractive rendering path
that can render snapshots or replay-derived figures without a live GUI event
loop. EGL/OSMesa or another offscreen path should be evaluated for that use
case separately from the interactive Qt canvas.

## Open Questions

- Can the current Qt/VisPy backend ever reliably disable swap interval on the
  target Windows machines, or will the driver/DWM path always clamp it?
- Does `QOpenGLWindow` materially reduce draw time while still embedding well
  enough for the workbench UI?
- How much of the measured 31-47 ms canvas draw is buffer swap/composition vs
  actual scene traversal and GL work?
- Should the frontend scheduler enforce one heavyweight render per turn across
  all panel types?
- What is the right public surface for render diagnostics so app authors can
  see refresh, paint, queue, and dropped/coalesced counts without reading raw
  logs?
