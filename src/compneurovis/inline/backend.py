"""Runtime backend actors for inline-mode sources."""

from __future__ import annotations

from collections.abc import Iterator
import time
from typing import Any, Callable

from compneurovis.backends.base import BackendBase
from compneurovis.backends.interaction import (
    SELECTED_ENTITY_ID_KEY,
    SELECTED_ENTITY_IDS_KEY,
    _selection_ids_from_internal,
)
from compneurovis.core.messages import EntityClicked, InvokeAction, Message, MessagePayload, Reset, ValueChange
from compneurovis.inline.data_producers import (
    SnapshotProducer,
    SeriesProducer,
    DerivedValueProducer,
)
from compneurovis.inline.interactions import ActionInteraction, ControlInteraction
from compneurovis.inline.widgets.surface import SurfaceBinding
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
        actions: list[ActionInteraction],
        series: list[SeriesProducer],
    ) -> None:
        self._source_controls = controls
        self._source_actions = actions
        self._source_series = series
        self._series_sampler = SeriesSampler(series)
        for control in controls:
            self._bind_source_control(control)

    def _bind_source_control(self, control: ControlInteraction) -> None:
        spec = control._control_spec()
        key = spec.resolved_value_key()
        self.values.bind(
            key,
            lambda actor, value, _control=control, _key=key: actor._apply_source_control(_control, _key, value),
            get=control.get,
            initial=spec.default_value(),
        )

    def _apply_source_control(self, control: ControlInteraction, key: str, value: Any) -> None:
        if control.apply(self, value):
            self.values.set(key, value)
            self._notify_source_value_changed(key, value)

    def _notify_source_value_changed(self, key: str, value: Any) -> None:
        del key, value

    def action_specs(self) -> dict[str, Any]:
        return {action._action_id: action._action_spec() for action in self._source_actions}

    def on_action(self, action_id: str, payload: dict[str, Any], context: Any) -> bool:
        del payload
        for action in self._source_actions:
            if action._action_id == action_id:
                action.fn(context)
                return True
        return False

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
        if history_id is None or (field_ids is not None and history_id not in field_ids):
            return
        history_enabled = getattr(self, "history_enabled", None)
        if callable(history_enabled) and not history_enabled():
            return
        read_display = getattr(self, "_read_display_values", None)
        init_history = getattr(self, "_initialize_series_history", None)
        series_replace = getattr(self, "_series_field_replace", None)
        if not (callable(read_display) and callable(init_history) and callable(series_replace)):
            return
        current_time = getattr(self, "_current_sim_time", None)
        time_value = current_time() if callable(current_time) else getattr(self, "_time", 0.0)
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
        actions: list[ActionInteraction],
        surfaces: list[SurfaceBinding] | None = None,
        fields: list[SnapshotProducer] | None = None,
        derived_values: list[DerivedValueProducer] | None = None,
        initial_values: list[tuple[str, Any]] | None = None,
        geometries: list[Any] | None = None,
        selection_modes: dict[str, bool] | None = None,
        step: Callable[[Any], None] | None,
        iterator: Iterator | None = None,
    ) -> None:
        super().__init__()
        self._series = series
        self._controls = controls
        self._actions = actions
        self._surfaces = [] if surfaces is None else surfaces
        self._fields = [] if fields is None else fields
        self._derived_values = [] if derived_values is None else derived_values
        self._initial_values = [] if initial_values is None else initial_values
        self._geometries = [] if geometries is None else geometries
        self._selection_modes = {} if selection_modes is None else dict(selection_modes)
        self.geometry = self._geometries[0] if len(self._geometries) == 1 else None
        self._geometry_by_entity_id = {
            str(entity_id): geometry
            for geometry in self._geometries
            for entity_id in getattr(geometry, "entity_ids", ())
        }
        self._step_fn = step
        self._iterator = iterator
        self._series_sampler = SeriesSampler(series)
        for control in self._controls:
            self._bind_source_control(control)
        self._done = False

    def initialize(self, app_spec) -> None:
        del app_spec
        updates: dict[str, Any] = {key: value for key, value in self._initial_values}
        for binding in self._derived_values:
            if binding.initial is not None:
                updates[binding.name] = binding.initial
        for key, value in updates.items():
            self.values.set(key, value)
        if updates:
            self.emit_update(ValueChange(updates))
    def _dispatch_action(self, action_id: str, payload: dict[str, Any]) -> bool:
        del payload
        for action in self._actions:
            if action._action_id == action_id:
                action.fn(self._interaction_context())
                return True
        return False

    def reset_field_history(self, field_ids: set | None = None) -> None:
        self._begin_field_history_reset(field_ids)
        for trace in self._series:
            if field_ids is None or trace._field_id in field_ids:
                self.emit_update(trace._replace_message().payload)
        for binding in self._fields:
            if field_ids is None or binding.field_id in field_ids:
                self.emit_update(binding.replace_payload())

    def handle(self, message: Message[MessagePayload]) -> None:
        payload = message.payload
        if isinstance(payload, Reset):
            self._done = False
            self.reset_field_history()
        elif isinstance(payload, ValueChange):
            self.values.apply(self, payload.updates)
        elif isinstance(payload, EntityClicked):
            self._handle_entity_clicked(payload.entity_id)
        elif isinstance(payload, InvokeAction):
            self._dispatch_action(payload.action_id, {})
    def _handle_entity_clicked(self, entity_id: str) -> None:
        selection_key = SELECTED_ENTITY_IDS_KEY
        current = _selection_ids_from_internal(self.values.get(selection_key))
        entity_id = str(entity_id)
        if self._selection_modes.get(selection_key, False):
            selected = [value for value in current if value != entity_id]
            if len(selected) == len(current):
                selected.append(entity_id)
        else:
            selected = [entity_id]

        geometry = self._geometry_by_entity_id.get(entity_id)
        label = geometry.label_for(entity_id) if geometry is not None else entity_id
        updates = {
            selection_key: selected,
            SELECTED_ENTITY_ID_KEY: entity_id,
            "selected_entity_label": label,
        }
        for key, value in updates.items():
            self.values.set(key, value)
        self.emit_update(ValueChange(updates))

    def is_active(self) -> bool:
        return True

    def tick(self) -> None:
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
                self.emit_update(binding.replace_payload())
        self._emit_derived_values()

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

