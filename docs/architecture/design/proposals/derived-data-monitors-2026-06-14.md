# Derived Data, Monitors, and Live Detectors — Design Proposal

**Date:** 2026-06-14
**Status:** Proposal (for review before implementation)
**Motivating workload:** the pharynx poster — parameter-space regime maps, representative traces, and the metrics that classify them. We want to *develop* the protocols and detectors live in CompNeuroVis, then reuse the exact same model + detector code in headless parameter sweeps.

---

## 1. What we're actually trying to build

The poster needs, per panel: a 2D parameter grid, a categorical regime label at every grid point, representative traces, and the metrics that defined the regimes. To produce that confidently we need to, **live in the viewer**:

1. Compute **derived metrics** from the running sim (plateau duration, threshold-crossing / spike count in a window, return-to-baseline, propagation fraction, …).
2. **Monitor** those metrics in whatever visualization fits — a line over time, a **live bar plot** across compartments, a status readout.
3. Drive derivations with **configurable inputs** (a threshold, a window length) we can adjust and *see the effect of*.
4. **Record** good parameter configurations and the ranges we explored to a file.
5. Run the **same** model + the **same** derivation/detector functions **headless** in a sweep, so the maps and the live tool cannot drift.

The earlier attempt baked all of this into a single opinionated `sim.detector(...)`. That was rejected, correctly: it assumes one workflow. This proposal replaces it with a small set of generic, composable primitives, where a "detector" is just *something you build* from them.

The non-goal (per poster guidance): this is workflow tooling, not the scientific result. Keep the primitives general; keep detector/threshold specifics in user code.

---

## 2. The organizing principle: everything shown is a field

CompNeuroVis already moves all data as **fields** (`FieldSpec` declared, `Field` live, mutated by `FieldReplace`/`FieldAppend`). The morphology colors a field; a line plot renders a field. So a *derived metric is just another field* the backend computes and emits, and *monitoring it* is just a view over that field.

That gives a clean three-role decomposition. Each role already has precedent in the codebase:

| Role | What it is | Existing precedent |
|---|---|---|
| **Input** | a value the user sets (threshold, window, param) | `control(...)`; `GridSliceOperatorSpec.position_state_key` (a draggable value) |
| **Producer** | emits a field each frame | `line_refs(refs=)` (raw NEURON refs), `line(record=fn)` (a per-frame sampler) |
| **View** | renders a field/source | `morphology(...)`, `line(source=...)` |

The proposal is to make **Producer** first-class and view-independent (today `record=` is welded onto `line`), add a **stateful per-frame hook**, and add **`bar`** as a second view kind. Inputs and recording reuse what exists.

---

## 3. Primitives

### 3.1 Producers — `derive(...)` and `on_frame(...)`

**`derive(name, fn, *, series, mode="append"|"replace", window=None, unit=None) -> TraceSource`**

Declares a derived field computed once per display frame by `fn`. `fn()` returns one value per `series`. `mode="append"` grows a time series (a metric over time); `mode="replace"` overwrites a snapshot vector (e.g. a per-compartment count for a bar). Returns a `TraceSource` (the same handle `morphology.selection` already returns) so any view consumes it via `source=`.

This is a direct generalization of the existing `line(record=fn)` path (`LineRecorder` in `inline.py`): same per-frame sampling in `_AttachBackend._emit_batch`, but the field is decoupled from the line view. `line(record=)` becomes sugar for `derive(...) → line(source=...)`.

```python
crossings = sim.derive(
    "crossings",
    fn=lambda: per_cell_crossings(bufs, threshold_value),  # one count per compartment
    series=CELL_NAMES,
    mode="replace",
)
sim.bar(source=crossings)            # live bar plot
```

`fn` is arbitrary Python closing over the model, rolling buffers, and input values. It is the *only* place metric logic lives — generic to any metric.

**`on_frame(fn)`** — a per-frame backend hook, `fn(ctx)`, run after each display step (arity auto-detected, consistent with `action`/`interactions`). For stateful or side-effecting derivations that don't map to a single field: maintain a buffer, run a classifier, `ctx.set_state("regime", …)`, `ctx.show_status(...)`. A **detector** is exactly this: `on_frame` running your existing `plateau_pipeline.extract_features` and publishing the classification.

`derive` is the declarative "this field = f(state) each frame"; `on_frame` is the imperative escape hatch. Both run in the backend worker, where the model and user code live (see §5).

### 3.2 Views — add `bar`

**`bar(name, *, source, ...)`** renders a field as a live bar chart (one bar per series/category). This is the one genuinely new piece of infrastructure: a new **view kind**, which today means touching the closed `PanelSpec.kind` enum and the frontend panel set. That is precisely the open-vocabulary / genericity-gap item from the 2026-06-13 analysis (§6 there). Two ways to land it:

- **(a) Minimal:** add `bar`/`BarViewSpec` to the existing enum + a pyqtgraph `BarGraphItem` panel, mirroring how `line_plot` works. Fast, but grows the closed set by one more hardcoded kind.
- **(b) Principled:** introduce the `kind → (validator, render capability)` **registry** the analysis recommends, and register `bar` as the first non-core kind. More work, but it's the change that lets *any* future view (bar, raster, heatmap/space-time, text readout) be added without editing core validation — and the poster itself wants a space-time propagation plot too.

Recommendation: **(b)** if we're going to add bar, raster, and a space-time heatmap for the poster anyway; **(a)** only if bar is the lone addition. This is the main decision this doc asks reviewers to weigh.

### 3.3 Inputs — `control`, and an optional overlay presentation

Thresholds/windows are `control(...)` values today (sliders), which already round-trip to the backend and are recordable. That is sufficient for derivations to read them.

The "draggable horizontal line on the trace plot" the discussion raised is an *input presentation*, not a new value type: the same scalar control rendered as a movable line **on a target plot** instead of a slider in the controls panel. Modeled as a control with an overlay presentation, it round-trips and records for free. Modeled as an operator (like `GridSliceOperatorSpec`), it is conceptually cleaner but operators are currently frontend-local and would need a frontend→backend value channel. **Deferred** — it is cosmetic over a control and not required for the first slices.

### 3.4 Recording — config snapshots + swept ranges

Genuinely generic and not detector-specific. A thin helper (or pure `action(...)` composition):

- **snapshot:** on a key, append `{t, controls:{id:value}, state:{selected binding keys}}` as a JSONL row. Captures both params and any published derived/classification state (so good configs land already labeled).
- **swept ranges:** track min/max each control was set to; a second key writes `{id:[lo,hi]}`. This is the "save the ranges I swept" output.

Whether this is a `record_config(...)` helper or left to user `action()` code is a minor call; it composes from existing controls + actions either way.

---

## 4. How a detector / metric / monitor composes

Nothing is detector-shaped in the framework. A plateau detector is user code:

```python
thr = {"threshold": -20.0, "min_dur": 10.0}
sim.control("threshold", get=lambda: thr["threshold"], set=lambda v: thr.__setitem__("threshold", v), min=-60, max=20)

buf_t, buf_v = [], []
def detect(ctx):
    from neuron import h
    buf_t.append(h.t); buf_v.append(model.pm4.v)        # own buffer + window
    res = extract_features(np.array(buf_t), np.array(buf_v), threshold=thr["threshold"], min_duration_ms=thr["min_dur"])
    ctx.set_state("regime", res.classification)
    ctx.show_status(f"pm4: {res.classification}")
sim.on_frame(detect)
```

A windowed spike/plateau **count** monitored as a live bar is a `derive(... mode="replace") → bar(source=...)`. A metric over **time** is `derive(... mode="append") → line(source=...)`. The threshold input feeds all of them; the snapshot records the config + `state["regime"]`.

---

## 5. Frontend / backend reality (why producers run backend-side)

In desktop mode the backend is a re-run of the user script in a worker process; the frontend is the generic Vispy window with **no user code**. So `fn`/`on_frame`/derivations — being user Python over the live model — must run in the **backend**. Inputs set in the frontend (slider, future overlay) reach the backend through the existing command round-trip (`SetControl`), exactly as controls do now. This is consistent with the analysis's "two-tier interaction": cheap cosmetic feedback can stay frontend-local, but anything that *drives a computation* travels through the bus. Derived fields are emitted by the backend like every other field; no new transport is required for §3.1–§3.4.

---

## 6. Sweep reuse (the payoff)

Because the model is already a plain object (`PharynxMuscleModel`) and the derivation/detector `fn`s are plain functions over `(t, v, **vars)`, the headless sweep is the same model + the same functions with no GUI:

```python
for gx in egl19_grid:
    for gy in exp2_grid:
        model = PharynxMuscleModel(); model.apply_control("G_BEGL19", gx); model.apply_control("G_EXP2", gy)
        t, v = run_protocol(model)                 # fixed current-clamp protocol
        regime = extract_features(t, v, **saved_thresholds).classification
        grid[gx, gy] = regime
```

The live tool and the sweep share the model and the classifier; "representative traces" are literally grid points re-run. A thin sweep harness (loop + fixed protocol + CSV) is Phase 3; it needs no new CompNeuroVis primitives, only the model+detector it already shares.

---

## 7. Staged plan

1. **`derive` + `on_frame`** (no new view kind). Generalize the `record=`/`LineRecorder` path into a view-independent producer; add the per-frame hook. Demo: a derived metric on a `line(source=...)` + a `on_frame` plateau classifier in the status bar. *Fully reversible, reuses existing field/frame machinery.*
2. **`bar` view** — via the open view registry (§3.2b) preferably, so raster / space-time heatmap follow cheaply for the propagation panel.
3. **Recording** — `record_config` snapshot + swept-range export (or document the `action()` composition).
4. **Sweep harness** — headless grid runner reusing model + detector → regime maps + representative traces + metadata.
5. *(Deferred)* draggable-overlay input presentation.

---

## 8. Decisions (resolved 2026-06-14)

1. **Bar view — minimal enum bump.** Add `BarPlotViewSpec` + panel kind `"bar_plot"` + `sim.bar(...)`, mirroring `LinePlotViewSpec` / `"line_plot"` / `sim.line`. No registry for now (revisit if raster/space-time pile up).
2. **`derive` is canonical**, `line(record=)` becomes sugar over it. Must stay performant: **sampling is split from evaluation** — the `over=` buffer gets a cheap append every frame, but `fn` runs throttled (`max_refresh_hz`), so a window metric is O(window) at ~4–10 Hz regardless of how many derives stack.
3. **Per-frame compute — rich `derive` only, no `on_frame`.** `derive` gains `over=<signal>` + `window=` (framework buffers, passes `fn(t, v)`) and `target="field" | "state"`. This covers metrics *and* detectors declaratively. `on_frame` is **not** added unless a genuinely imperative case appears later.
4. **Recording — generic `on_control(fn(id, value))` hook + control enumeration** (`ctx.controls()`), not a `record_config` helper. Snapshot and swept-range tracking are composed in user code (~15 lines), keeping the framework free of a recording schema. Range-tracking was the only hard-to-compose part; the `on_control` hook supplies it.

### Implementation slices

1. **`derive` + `on_control`** (no new view kind). `DerivedField` runtime (buffer + throttled eval), `derive(...)` → `TraceSource` (field target) or a state key (state target), `on_control(...)` + `ctx.controls()`. Demo: a windowed metric on `line(source=...)` and a detector via `derive(target="state")`, plus range-tracking via `on_control`.
2. **`bar`** view (enum bump) + `sim.bar(source=...)`.
3. **Sweep harness** reusing model + derive/detector fns headless.
