# NEURON / Jaxley backend-layer inventory

Enumeration of every class + method across the `backend`, `inline`, and `source`
modules for both engines, plus the shared pieces they lean on. Intended to make
the shared-vs-specific split visible so we can decide the cleanest decomposition.

## File sizes

| File | Lines |
|------|------:|
| `backends/neuron/backend.py` | 738 |
| `backends/neuron/source.py` | 927 |
| `backends/neuron/inline.py` | 488 |
| `backends/jaxley/backend.py` | 582 |
| `backends/jaxley/inline.py` | 138 |
| `backends/jaxley/source.py` | 96 |
| `inline/backend.py` (shared: `SourceBackendMixin`, `InlineBackend`) | 212 |

---

## 1. Base backend classes — alignment

`NeuronBackend(BackendBase, ABC)` vs `JaxleyBackend(BackendBase, ABC)`.
Grouped by whether the method is shared (same name/role in both) or engine-only.

### Shared surface (present in BOTH, same name & role — much of it byte-identical)

Runtime / lifecycle:
- `__init__`
- `build_startup_data`
- `initialize`
- `tick`
- `_emit_batch`
- `_sample_step`
- `sim_ms_per_frame`
- `idle_sleep`
- `is_active`
- `_resolved_field_max_samples`

Display / history fields:
- `display_field_id`, `history_field_id`
- `display_unit`, `history_unit`
- `set_history_enabled`, `history_enabled`
- `_read_display_values`, `_read_voltage`
- `_display_field_replace`

Selection-trace history (**verified byte-identical except neuron adds one cache-invalidation line**):
- `_initialize_trace_history`
- `_clear_trace_history`
- `_preferred_trace_entity_ids`
- `_capture_trace_entity`
- `_trace_field_snapshot`
- `_trace_field_replace`
- `_trim_selected_trace_history`
- `_append_selected_trace_history`

Interaction dispatch:
- `control_specs`, `control_values`, `action_specs`
- `apply_control`, `apply_action`
- `on_action`, `on_key_press`, `on_entity_clicked`, `should_capture_trace_on_click`
- `_interaction_context`, `_dispatch_action`, `handle`

### NEURON-only

Model build / config:
- `build_sections`, `setup_model`
- `DisplayConfig` (dataclass)
- `_require_display`
- `_initialize_model`

Recording (PtrVector fast path):
- `record`, `record_many`, `on_recorded_samples`, `recorded_values`
- `_prepare_recorders`, `_rebuild_recorded_ptrs`, `_read_recorded_values`

On-demand selection-trace sampling (PtrVector):
- `_invalidate_trace_sampler`, `_rebuild_trace_sampler`, `_read_selected_trace_values`
- `_emit_on_demand_display_and_trace`
- `_append_selected_trace_history_values` (per-value variant of the shared `_append_selected_trace_history`)

Selection state:
- `_set_initial_selection_state`, `_selected_entity_ids_from_state`

Misc:
- `_sample`

### JAXLEY-only

Model build / config:
- `build_cells`, `build_network`, `setup_model`, `cell_names`
- `_initialize_model`

Live parameter/external refresh (jax re-jit):
- `_externals_for_step`
- `_reinitialize_runtime`
- `refresh_runtime_parameters`, `refresh_runtime_externals`

State read:
- `_read_state`

> **Takeaway:** the entire "Shared surface" block above is one runtime living in
> two files. The engine-specific blocks are genuinely different (NEURON =
> PtrVector recording + on-demand sampling; Jaxley = jax re-jit refresh). NEURON
> carries substantially more machinery than Jaxley.

---

## 2. Source backends — alignment

Both inherit `SourceBackendMixin` (shared) + their engine backend.

### `SourceBackendMixin` (in `inline/backend.py`) — already shared

- `_init_source_bindings`
- `control_specs`, `control_values`, `_control_binding_value`
- `_apply_backend_control`, `_notify_source_control_changed`, `apply_control`
- `action_specs`, `on_action`
- `_emit_source_reset_fields`, `_emit_source_trace_updates`
- `idle_sleep`

### `neuron/source.py :: _SourceBackend(SourceBackendMixin, NeuronBackend)` — ~24 methods

- `__init__`, `build_sections`, `initialize`
- `control_specs`, `control_values`, `apply_control` (overrides), `_apply_backend_control`, `_notify_source_control_changed`
- `should_capture_trace_on_click`, `_emit_source_reset_fields`
- `_uses_source_step`, `_sample_source_step`, `_sample_step`, `_emit_batch`
- `_observe_derives`, `_update_derives`
- `_recorder_replace`, `_emit_segment_variable_replaces`
- `on_entity_clicked`, `on_key_press`, `handle`
- `tick`, `_flush_pending`, `idle_sleep`

### `jaxley/source.py :: _SourceBackend(SourceBackendMixin, JaxleyBackend)` — 4 methods

- `__init__`, `build_cells`, `setup_model`, `_emit_batch`

> **Takeaway:** Jaxley's source backend is 4 methods — it needs nothing beyond the
> mixin + base. NEURON's is ~24 because of derives, recorders, segment-variable
> replaces, `flush_dt` batching, custom step, and on-demand sampling. The
> asymmetry is real neuron functionality, not accidental duplication.

---

## 3. Inline sources (authoring vocabulary)

### `neuron/inline.py :: NeuronInlineSource(InlineSourceBase)`

Authoring methods: `morphology`, `record`, `line` (via base?), `action`,
`interactions`, `derive`, `derive_value`, `on_control`, `_compose_app_spec_for_backend`

Support classes in the module: `NeuronActionBinding`, `LineRecorder`, `DerivedField`
Helpers: `_time_coord`, `_coerce_series_initial`

### `neuron/source.py :: NeuronSource(NeuronInlineSource)`

Adds source-specific bindings: `segment_variable_display`, `segment_variable_history`,
`record_refs`, `_make_backend`
Support classes: `SegmentVariableDisplayBinding` (+Handle), `SegmentVariableHistoryBinding` (+Handle),
`NeuronRefRecorder`, `_SourceStep`

### `jaxley/inline.py :: JaxleyInlineSource(InlineSourceBase)`

Authoring methods: `morphology`, `control`, `_compose_app_spec_for_backend`
Support class: `JaxleyControlBinding`

### `jaxley/source.py :: JaxleySource(JaxleyInlineSource)`

`__init__`, `_make_backend` only.

---

## 4. Observations / open questions

- **The base backends are where the duplication lives**, not the inline/source
  layers. The "Shared surface" list in §1 is ~25 methods duplicated across
  `neuron/backend.py` and `jaxley/backend.py`, several verified identical.
- **Jaxley side is already lean** (source = 96 lines, inline = 138, source
  backend = 4 methods). NEURON side is heavy because of real extra features.
- **`JaxleyInlineSource` exposes `morphology` + `control` only** — `history` is
  gone; the example now uses the **generic `src.line`** from `InlineSourceBase`.
  So Jaxley already reuses the base line construct — only NEURON still carries its
  own `record`/`record_refs`/`line` variants (for the PtrVector sampler).
- **`SourceBackendMixin` already factors the source-side control/action plumbing**
  — good precedent; the base backends have no equivalent shared home for the
  display/history/trace runtime.
- Neuron's on-demand trace path (`_read_selected_trace_values`,
  `_emit_on_demand_display_and_trace`, `_append_selected_trace_history_values`)
  is a parallel copy of the shared trace path optimized with PtrVector — a likely
  spot to collapse behind one interface.
