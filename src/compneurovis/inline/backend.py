"""Runtime backend actors for inline-mode sources."""

from __future__ import annotations

from collections.abc import Iterator
import time
from typing import Any, Callable

from compneurovis.backends.base import BackendBase
from compneurovis.core.messages import InvokeAction, Message, MessagePayload, ValueChange
from compneurovis.inline.bindings import (
    ActionBinding,
    ArrayFieldBinding,
    ControlBinding,
    DerivedValueBinding,
    SurfaceBinding,
    TraceBinding,
    TraceSampler,
    emit_trace_updates,
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
        controls: list[ControlBinding],
        actions: list[ActionBinding],
        traces: list[TraceBinding],
    ) -> None:
        self._source_controls = controls
        self._source_actions = actions
        self._source_traces = traces
        self._trace_sampler = TraceSampler(traces)
        for control in controls:
            self._bind_source_control(control)

    def _bind_source_control(self, control: ControlBinding) -> None:
        spec = control._control_spec()
        key = spec.resolved_value_key()
        self.values.bind(
            key,
            lambda actor, value, _control=control, _key=key: actor._apply_source_control(_control, _key, value),
            get=control.get,
            initial=spec.default_value(),
        )

    def _apply_source_control(self, control: ControlBinding, key: str, value: Any) -> None:
        if control.apply(self, value):
            self.values.set(key, value)
            self._notify_source_value_changed(key, value)

    def _notify_source_value_changed(self, key: str, value: Any) -> None:
        del key, value

    def action_specs(self) -> dict[str, Any]:
        return {action._action_id: action._action_spec() for action in self._source_actions}

    def on_action(self, action_id: str, payload: dict[str, Any], context: Any) -> bool:
        for action in self._source_actions:
            if action._action_id == action_id:
                invoke = getattr(action, "invoke", None)
                if callable(invoke):
                    invoke(context, payload if isinstance(payload, dict) else {})
                else:
                    action.fn(context)
                if action.resets_fields:
                    self._emit_source_reset_fields()
                return True
        return False

    def _emit_source_reset_fields(self) -> None:
        for trace in self._source_traces:
            self.emit_update(trace._replace_message().payload)

    def _emit_source_trace_updates(self, *, auto_sample: bool = False) -> None:
        for trace in self._source_traces:
            trace._begin_frame()
            trace._sample()
        emit_trace_updates(self, self._source_traces, auto_sample=auto_sample)

    def idle_sleep(self) -> float:
        return self._SOURCE_FRAME_S

class InlineBackend(SourceBackendMixin, BackendBase):
    """Backend actor for pure-Python inline sources."""

    _FRAME_MS = 1000.0 / 60.0

    def __init__(
        self,
        *,
        traces: list[TraceBinding],
        controls: list[ControlBinding],
        actions: list[ActionBinding],
        surfaces: list[SurfaceBinding] | None = None,
        fields: list[ArrayFieldBinding] | None = None,
        derived_values: list[DerivedValueBinding] | None = None,
        initial_values: list[tuple[str, Any]] | None = None,
        step: Callable[[Any], None] | None,
        iterator: Iterator | None = None,
    ) -> None:
        super().__init__()
        self._traces = traces
        self._controls = controls
        self._actions = actions
        self._surfaces = [] if surfaces is None else surfaces
        self._fields = [] if fields is None else fields
        self._derived_values = [] if derived_values is None else derived_values
        self._initial_values = [] if initial_values is None else initial_values
        self._step_fn = step
        self._iterator = iterator
        self._trace_sampler = TraceSampler(traces)
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
        for action in self._actions:
            if action._action_id == action_id:
                action.fn(self._interaction_context())
                if action.resets_fields:
                    self._emit_field_replaces()
                return True
        return False

    def _emit_field_replaces(self) -> None:
        for trace in self._traces:
            self.emit_update(trace._replace_message().payload)
        for surface in self._surfaces:
            self.emit_update(surface._replace_message().payload)
        for binding in self._fields:
            self.emit_update(binding.replace_payload())
    def handle(self, message: Message[MessagePayload]) -> None:
        payload = message.payload
        if isinstance(payload, ValueChange):
            self.values.apply(self, payload.updates)
        elif isinstance(payload, InvokeAction):
            self._dispatch_action(payload.action_id, {})
    def is_active(self) -> bool:
        return True

    def tick(self) -> None:
        self._trace_sampler._begin_update()
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
        emit_trace_updates(self, self._traces)
        for surface in self._surfaces:
            if surface.read is not None:
                self.emit_update(surface._replace_message().payload)
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
