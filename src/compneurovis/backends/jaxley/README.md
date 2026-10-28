---
title: Jaxley Backend
summary: Jaxley backend, source authoring/runtime, geometry conversion, IO, and layout.
---

# Jaxley Backend

`compneurovis.backends.jaxley` provides a Jaxley-native backend with the same
source-level shape as the NEURON integration:

- `JaxleyBackend` for low-level actor execution
- `JaxleySource` and `source/` for source-level authoring
- `geometry.py`, `io/`, and `layout.py` for Jaxley-specific conversion and IO

CompNeuroVis preserves the embedding application's JAX precision policy by
default. Pass `jax_enable_x64=True` or `False` to `jaxley.source(...)` only when
that source should explicitly select a precision mode in its backend process.

The backend publishes its native voltage stream as:

- `segment_display`: latest values for current morphology coloring
- `segment_history`: retained trace history for on-demand trace inspection

Several morphology widgets may consume those shared data fields. Each widget still
owns a distinct canonical selection: initialization and clicks route by the exact
selection id and do not overwrite another panel's state. On-demand history retains
the stable union of entities selected through any of those widgets.

Use `history_capture_mode=HistoryCaptureMode.FULL` when the app needs full
all-entity history for retrospective trace selection or playback.

To sample additional channel states per step, override two hooks instead of `advance()`:

- `_sample_step() -> Any` - called once per simulation step; return whatever per-step data you need.
- `_emit_batch(times_array, steps)` - called once per display update batch; `steps` is a list of whatever `_sample_step()` returned.

Use `_read_state(state_name)` inside `_sample_step()` to read any Jaxley channel variable at the display compartment indices. State keys follow Jaxley's `ChannelName_statename` convention (e.g. `'HH_m'`, `'HH_n'`, `'HH_h'`). All channel states are available in `self._state` after each step without any additional recording setup.
