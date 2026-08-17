"""Runtime backend actors for inline-mode sources."""

from __future__ import annotations

from collections.abc import Iterator
import time
from typing import Any, Callable, Mapping

from compneurovis.backends.base import BackendBase
from compneurovis.core.messages import (
    ControlPatch,
    Message,
    MessagePayload,
    Reset,
    ValueChange,
)
from compneurovis.core.runtime.performance import perf_log, perf_logging_enabled
from compneurovis.inline.data_producers import (
    SnapshotProducer,
    SeriesProducer,
    DerivedValueProducer,
)
from compneurovis.inline.interactions import (
    KeyBindingInteraction,
    ControlInteraction,
    ClickHandlerBinding,
    PointerInteractionHandlerBinding,
)
from compneurovis.inline.sampling import (
    SeriesSampler,
    emit_series_updates,
)


class SourceBackendMixin:
    """Shared runtime behavior for simulator-backed inline sources.

    NEURON and Jaxley differ in how they step and sample their simulators. Their
    source wrappers do not differ in how authored controls, actions, or callable
    trace panels are registered and dispatched, so that plumbing lives here.
    """

    _SOURCE_FRAME_S = 1.0 / 60.0

    def _init_source_bindings(
        self,
        *,
        controls: list[ControlInteraction],
        key_bindings: list[KeyBindingInteraction] | None = None,
        series: list[SeriesProducer],
        fields: list[SnapshotProducer],
        click_handlers: list[ClickHandlerBinding],
        pointer_interaction_handlers: list[PointerInteractionHandlerBinding],
    ) -> None:
        self._source_controls = controls
        self._source_key_bindings = (
            [] if key_bindings is None else key_bindings
        )
        self._source_series = series
        self._source_fields = fields
        self._source_click_handlers = click_handlers
        self._source_pointer_interaction_handlers = pointer_interaction_handlers
        self._series_sampler = SeriesSampler(series)
        for control in controls:
            self._bind_source_control(control)

    def _bind_source_control(self, control: ControlInteraction) -> None:
        spec = control._control_spec()
        key = spec.resolved_value_key()
        control._bind_state_updates(
            lambda updates, _control_id=spec.id: self.emit_update(
                ControlPatch(_control_id, updates)
            )
        )
        self.values.bind(
            key,
            lambda actor,
            value,
            _control=control,
            _key=key: actor._apply_source_control(_control, _key, value),
            get=control.get,
            initial=spec.default_value(),
        )

    def _apply_source_control(
        self, control: ControlInteraction, key: str, value: Any
    ) -> None:
        if control.apply(self, value):
            self.values.set(key, value)
            self._notify_source_value_changed(key, value)

    def _notify_source_value_changed(self, key: str, value: Any) -> None:
        del key, value

    def on_invoke(self, interaction_id: str, payload: dict[str, Any], context: Any) -> bool:
        del context
        return self._invoke_source_interaction(interaction_id, payload)

    def _invoke_source_interaction(
        self, interaction_id: str, payload: dict[str, Any]
    ) -> bool:
        """Activate whichever invocable interaction owns this canonical id."""

        for control in self._source_controls:
            if control.is_trigger and control._control_id == interaction_id:
                return control.invoke(self, payload)
        for binding in self._source_key_bindings:
            if binding._binding_id == interaction_id:
                return binding.invoke(self, payload)
        return False

    def intercept_click(self, event: Any, context: Any) -> bool:
        interaction = self._click_specs[event.interaction_id]
        for binding in self._source_click_handlers:
            if not binding.handles(event.interaction_id, interaction.result_kind):
                continue
            if binding.fn(context, event):
                return True
        return False

    def on_pointer_interaction(self, event: Any, context: Any) -> bool:
        for binding in self._source_pointer_interaction_handlers:
            if binding.handles(event.interaction_id):
                binding.fn(context, event)
                return True
        return False

    def replace_field_data(
        self,
        field_id: str,
        values: Any,
        *,
        coords: Mapping[str, Any] | None = None,
    ) -> bool:
        """Replace source-owned snapshot state and publish one atomic update."""
        for binding in self._source_fields:
            if binding.field_id != field_id:
                continue
            if binding.read is not None:
                raise ValueError(
                    f"Cannot set_data() on continuously sampled field {field_id!r}"
                )
            previous_values = binding.values
            previous_coords = binding.coords
            previous_includes_coords = binding.replace_includes_coords
            binding.values = values
            if coords is not None:
                binding.coords = dict(coords)
                binding.replace_includes_coords = True
            try:
                payload = binding.replace_payload()
            except Exception:
                binding.values = previous_values
                binding.coords = previous_coords
                binding.replace_includes_coords = previous_includes_coords
                raise
            self.emit_update(payload)
            return True
        return False

    def _emit_source_snapshot_updates(self) -> None:
        for binding in self._source_fields:
            if binding.read is not None:
                self.emit_update(binding.replace_payload())

    def reset_field_history(self, field_ids: set | None = None) -> None:
        """Re-emit one-sample replacements for selected history fields.

        This backs ``ctx.clear()``: clear accumulated plot/history data and make
        subsequent samples continue from the current model time. It does not
        mutate the simulator model or call a simulator reset.
        """
        self._begin_field_history_reset(field_ids)
        for trace in self._source_series:
            if field_ids is None or trace._field_id in field_ids:
                self.emit_update(trace._replace_message().payload)
        self._reset_backend_field_history(field_ids)

    def _begin_field_history_reset(self, field_ids: set | None) -> None:
        del field_ids
        reset_buffers = getattr(self, "_reset_pending_output_buffers", None)
        if callable(reset_buffers):
            reset_buffers()

    def _reset_backend_field_history(self, field_ids: set | None) -> None:
        """Reset backend-specific field producers (recorders, histories)."""
        history_field_id = getattr(self, "history_field_id", None)
        history_id = history_field_id() if callable(history_field_id) else None
        if history_id is None or (
            field_ids is not None and history_id not in field_ids
        ):
            return
        history_enabled = getattr(self, "history_enabled", None)
        if callable(history_enabled) and not history_enabled():
            return
        read_display = getattr(self, "_read_display_values", None)
        init_history = getattr(self, "_initialize_series_history", None)
        series_replace = getattr(self, "_series_field_replace", None)
        if not (
            callable(read_display)
            and callable(init_history)
            and callable(series_replace)
        ):
            return
        current_time = getattr(self, "_current_sim_time", None)
        time_value = (
            current_time() if callable(current_time) else getattr(self, "_time", 0.0)
        )
        display_values = read_display()
        if hasattr(self, "_last_time_value"):
            self._last_time_value = float(time_value)
        init_history(float(time_value), display_values)
        self.emit_update(series_replace())

    def _emit_source_series_updates(self, *, auto_sample: bool = False) -> None:
        for trace in self._source_series:
            trace._begin_frame()
            trace._sample()
        emit_series_updates(self, self._source_series, auto_sample=auto_sample)

    def idle_sleep(self) -> float:
        return self._SOURCE_FRAME_S


class InlineBackend(SourceBackendMixin, BackendBase):
    """Backend actor for pure-Python inline sources."""

    _FRAME_MS = 1000.0 / 60.0

    def __init__(
        self,
        *,
        series: list[SeriesProducer],
        controls: list[ControlInteraction],
        key_bindings: list[KeyBindingInteraction] | None = None,
        click_handlers: list[ClickHandlerBinding] | None = None,
        pointer_interaction_handlers: list[
            PointerInteractionHandlerBinding
        ] | None = None,
        fields: list[SnapshotProducer] | None = None,
        derived_values: list[DerivedValueProducer] | None = None,
        initial_values: list[tuple[str, Any]] | None = None,
        step: Callable[[Any], None] | None,
        iterator: Iterator | None = None,
    ) -> None:
        super().__init__()
        self._series = series
        self._controls = controls
        self._fields = [] if fields is None else fields
        self._init_source_bindings(
            controls=controls,
            key_bindings=key_bindings,
            series=series,
            fields=self._fields,
            click_handlers=[] if click_handlers is None else click_handlers,
            pointer_interaction_handlers=(
                []
                if pointer_interaction_handlers is None
                else pointer_interaction_handlers
            ),
        )
        self._derived_values = [] if derived_values is None else derived_values
        self._initial_values = [] if initial_values is None else initial_values
        self.geometry = None
        self._step_fn = step
        self._iterator = iterator
        self._series_sampler = SeriesSampler(series)
        self._perf_window_started = time.monotonic()
        self._perf_tick_count = 0
        self._perf_tick_ms = 0.0
        self._perf_field_count = 0
        self._perf_field_build_ms = 0.0
        self._perf_field_bytes = 0
        self._perf_logged_fields: set[str] = set()
        self._done = False

    def initialize(self, app_spec) -> None:
        super().initialize(app_spec)
        updates: dict[str, Any] = {key: value for key, value in self._initial_values}
        for binding in self._derived_values:
            if binding.initial is not None:
                updates[binding.name] = binding.initial
        for key, value in updates.items():
            self.values.set(key, value)
        if updates:
            self.emit_update(ValueChange(updates))

    def _dispatch_invoke(self, interaction_id: str, payload: dict[str, Any]) -> bool:
        return self.on_invoke(interaction_id, payload, self._interaction_context())

    def reset_field_history(self, field_ids: set | None = None) -> None:
        self._begin_field_history_reset(field_ids)
        for trace in self._series:
            if field_ids is None or trace._field_id in field_ids:
                self.emit_update(trace._replace_message().payload)
        for binding in self._fields:
            if field_ids is None or binding.field_id in field_ids:
                self.emit_update(binding.replace_payload())

    def handle_backend_message(self, message: Message[MessagePayload]) -> None:
        payload = message.payload
        if isinstance(payload, Reset):
            self._done = False
            self.reset_field_history()

    def is_active(self) -> bool:
        return True

    def tick(self) -> None:
        perf_enabled = perf_logging_enabled()
        tick_started = time.monotonic() if perf_enabled else 0.0
        self._series_sampler._begin_update()
        if self._step_fn is not None and not self._done:
            try:
                self._step_fn(self._interaction_context())
            except StopIteration:
                self._done = True
        elif self._iterator is not None and not self._done:
            try:
                next(self._iterator)
            except StopIteration:
                self._done = True
        emit_series_updates(self, self._series)
        # Surface data producers live in ``self._fields`` (declared via
        # ``_declare_grid_field``), so the field loop below covers them too.
        for binding in self._fields:
            if binding.read is not None:
                field_started = time.monotonic() if perf_enabled else 0.0
                payload = binding.replace_payload()
                if perf_enabled:
                    field_build_ms = (time.monotonic() - field_started) * 1000.0
                    values_bytes = int(payload.values.nbytes)
                    coords_bytes = sum(
                        int(coord.nbytes) for coord in (payload.coords or {}).values()
                    )
                    payload_bytes = values_bytes + coords_bytes
                    self._perf_field_count += 1
                    self._perf_field_build_ms += field_build_ms
                    self._perf_field_bytes += payload_bytes
                    if binding.field_id not in self._perf_logged_fields:
                        self._perf_logged_fields.add(binding.field_id)
                        perf_log(
                            "inline_backend",
                            "snapshot_field",
                            field_id=binding.field_id,
                            values_shape=payload.values.shape,
                            values_bytes=values_bytes,
                            coords_bytes=coords_bytes,
                            payload_bytes=payload_bytes,
                            includes_coords=payload.coords is not None,
                        )
                self.emit_update(payload)
        self._emit_derived_values()
        if perf_enabled:
            self._record_perf_tick(tick_started)

    def _record_perf_tick(self, tick_started: float) -> None:
        now = time.monotonic()
        self._perf_tick_count += 1
        self._perf_tick_ms += (now - tick_started) * 1000.0
        elapsed_s = now - self._perf_window_started
        if elapsed_s < 1.0:
            return
        tick_count = self._perf_tick_count
        field_count = self._perf_field_count
        perf_log(
            "inline_backend",
            "tick_window",
            window_s=round(elapsed_s, 3),
            tick_count=tick_count,
            tick_hz=round(tick_count / elapsed_s, 3),
            tick_ms_total=round(self._perf_tick_ms, 3),
            tick_ms_avg=round(self._perf_tick_ms / max(tick_count, 1), 3),
            snapshot_count=field_count,
            snapshot_build_ms_total=round(self._perf_field_build_ms, 3),
            snapshot_build_ms_avg=round(
                self._perf_field_build_ms / max(field_count, 1), 3
            ),
            snapshot_bytes=self._perf_field_bytes,
            snapshot_mib_s=round(
                self._perf_field_bytes / elapsed_s / (1024.0 * 1024.0), 3
            ),
        )
        self._perf_window_started = now
        self._perf_tick_count = 0
        self._perf_tick_ms = 0.0
        self._perf_field_count = 0
        self._perf_field_build_ms = 0.0
        self._perf_field_bytes = 0

    def _emit_derived_values(self) -> None:
        if not self._derived_values:
            return
        now = time.monotonic()
        updates: dict[str, Any] = {}
        for binding in self._derived_values:
            if binding.due(now):
                updates[binding.name] = binding.evaluate(now)
        for key, value in updates.items():
            self.values.set(key, value)
        if updates:
            self.emit_update(ValueChange(updates))

    def idle_sleep(self) -> float:
        return self._FRAME_MS / 1000.0


__all__ = ["InlineBackend", "SourceBackendMixin"]
