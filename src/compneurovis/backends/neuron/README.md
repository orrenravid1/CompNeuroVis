---
title: NEURON Backend Package
summary: NEURON backend, source authoring/runtime, geometry conversion, IO, and layout.
---

# NEURON Backend Package

This package contains:

- `NeuronSceneBuilder`
- `NeuronSession`
- `utils/` for NEURON-specific SWC import, JSON round-trip, and layout helpers

By default, the NEURON backend splits latest live display state from retained trace history:

- `segment_display` for current morphology coloring
- `segment_history` for trace history

The current sampled quantity is voltage by default, but those field ids are role-based rather than voltage-specific. Use `HistoryCaptureMode.FULL` when the app needs full all-entity history for retrospective trace selection or playback.

Subclasses can call `record(name, ref)` or `record_many(names, refs)` during `_prepare_recorders()` to sample additional NEURON variable refs through the same fixed-size `PtrVector` cadence as the morphology display. Override `on_recorded_samples(times, values)` to emit those batched samples as custom fields without maintaining unbounded `h.Vector.record()` histories.

To sample multiple quantities per step (e.g. gating variables, input current), override two hooks instead of `advance()`:

- `_sample_step() -> Any` - called once per `fadvance()` step; return whatever per-step data you need.
- `_emit_batch(times_array, steps)` - called once per display update batch; `steps` is a list of whatever `_sample_step()` returned. Emit your custom `FieldAppend` events here.

Recording via `record()`/`on_recorded_samples()` is handled automatically by the base `advance()` loop regardless of what these hooks return. See `hh_section_inspector.py` for a worked example.
