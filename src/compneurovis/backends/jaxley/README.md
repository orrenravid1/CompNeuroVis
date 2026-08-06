---
title: Jaxley Backend
summary: Jaxley backend, source authoring/runtime, geometry conversion, IO, and layout.
---

# Jaxley Backend

`compneurovis.backends.jaxley` provides a Jaxley-native live session with the same high-level shape as the NEURON backend:

- `JaxleySession`: subclass this to build cells, configure the network, and emit live updates
- `JaxleySceneBuilder`: converts Jaxley network compartment geometry into `MorphologyGeometry` plus the default morphology/trace views
- `utils/`: Jaxley-specific SWC import, cache, layout, and geometry helpers

By default, the backend splits:

- `segment_display`: latest values for current morphology coloring
- `segment_history`: retained trace history for on-demand trace inspection

The current sampled quantity is voltage by default, but those field ids are role-based rather than voltage-specific. Use `history_capture_mode=HistoryCaptureMode.FULL` when the app needs full all-entity history for retrospective trace selection or playback.

To sample additional channel states per step, override two hooks instead of `advance()`:

- `_sample_step() -> Any` - called once per simulation step; return whatever per-step data you need.
- `_emit_batch(times_array, steps)` - called once per display update batch; `steps` is a list of whatever `_sample_step()` returned.

Use `_read_state(state_name)` inside `_sample_step()` to read any Jaxley channel variable at the display compartment indices. State keys follow Jaxley's `ChannelName_statename` convention (e.g. `'HH_m'`, `'HH_n'`, `'HH_h'`). All channel states are available in `self._state` after each step without any additional recording setup.
