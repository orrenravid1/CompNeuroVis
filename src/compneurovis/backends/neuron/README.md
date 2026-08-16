---
title: NEURON Backend Package
summary: NEURON backend, source authoring/runtime, geometry conversion, IO, and layout.
---

# NEURON Backend Package

This package contains:

- `NeuronBackend` for low-level actor execution
- `NeuronSource` and `source/` for source-level authoring and optimized recording
- `geometry.py`, `io/`, and `layout.py` for NEURON-specific conversion and IO

The low-level `NeuronBackend` can optionally publish one conventional segment
sampling stream, split into latest state and retained history:

- `segment_display` for the latest sampled values
- `segment_history` for retained selected-entity history

Those ids are low-level role conventions, not voltage semantics and not widget
identity. Normal `NeuronSource.morphology(...)` authoring requires one explicit
current `variable` and allocates ordinary unique display and history fields for
every morphology widget. An app may atomically replace that widget's current
data, unit, limits, and palette with `morphology.set_display(...)`; the widget
does not own a registry of alternative displays. Two morphology panels therefore
keep independent colors, selections, and selection histories; neither one
overwrites a backend-global display slot.

Native `PtrVector` collection remains in use. A compiled reader is a property of
the model and its geometry rather than of any view, so `segment_readers.py`
owns them on the backend: several morphologies over one geometry share a single
reader per source, keyed by the source object itself. Compiling one costs a
pointer lookup per visual segment, so it is cached for the backend's lifetime
and built on first read by default. `source.prepare_segment_values(...)` moves
that cost into startup instead, and neither names nor requires a morphology —
prepare a source before, or without, any view that displays it. Sources with no
native pointer (a callable returning a plain value) are recorded as non-native
and read segment by segment; explicit per-segment arrays need no reader at all.

Use `HistoryCaptureMode.FULL` on a low-level segment sampler when the app needs
full all-entity history for retrospective selection or playback.

Subclasses can call `record(name, ref)` or `record_many(names, refs)` from
`setup_model(...)` (or while extending recorder preparation) to sample additional
NEURON references through a fixed-size `PtrVector`. Override
`on_recorded_samples(times, values)` to consume those batched samples without
maintaining unbounded `h.Vector.record()` histories. A low-level backend may run
and record without declaring a segment display sampler or any panel.

To sample multiple quantities per step (e.g. gating variables, input current), override two hooks instead of `advance()`:

- `_sample_step() -> Any` - called once per `fadvance()` step; return whatever per-step data you need.
- `_emit_batch(times_array, steps)` - called once per display update batch; `steps` is a list of whatever `_sample_step()` returned. Emit your custom `FieldAppend` events here.

Recording via `record()`/`on_recorded_samples()` is handled automatically by the base `advance()` loop regardless of what these hooks return. See `hh_section_inspector.py` for a worked example.
