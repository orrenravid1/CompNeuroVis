"""Runtime backend actors for inline-mode sources."""

from __future__ import annotations

from collections.abc import Iterator
import time
from typing import Any, Callable

from compneurovis.backends.base import BackendBase
from compneurovis.core.messages import BindingValuePatch, InvokeAction, Message, MessagePayload, SetControl
from compneurovis.inline.bindings import (
    ActionBinding,
    ControlBinding,
    DerivedValueBinding,
    SurfaceBinding,
    TraceBinding,
    TraceSampler,
    emit_trace_updates,
)


class InlineBackend(BackendBase):
    """Backend actor for pure-Python inline sources."""

    _FRAME_MS = 1000.0 / 60.0

    def __init__(
        self,
        *,
        traces: list[TraceBinding],
        controls: list[ControlBinding],
        actions: list[ActionBinding],
        surfaces: list[SurfaceBinding] | None = None,
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
        self._derived_values = [] if derived_values is None else derived_values
        self._initial_values = [] if initial_values is None else initial_values
        self._step_fn = step
        self._iterator = iterator
        self._trace_sampler = TraceSampler(traces)
        self._done = False

    def initialize(self, app_spec) -> None:
        del app_spec
        updates: dict[str, Any] = {key: value for key, value in self._initial_values}
        for binding in self._derived_values:
            if binding.initial is not None:
                updates[binding.name] = binding.initial
        if updates:
            self.emit_update(BindingValuePatch(updates))

    def control_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for control in self._controls:
            get = getattr(control, "get", None)
            if get is not None:
                values[control._control_id] = get()
        return values

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

    def handle(self, message: Message[MessagePayload]) -> None:
        payload = message.payload
        if isinstance(payload, SetControl):
            for control in self._controls:
                if control._control_id == payload.control_id:
                    control.apply(self, payload.value)
                    break
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
        self._emit_derived_values()

    def _emit_derived_values(self) -> None:
        if not self._derived_values:
            return
        now = time.monotonic()
        updates: dict[str, Any] = {}
        for binding in self._derived_values:
            if binding.due(now):
                updates[binding.name] = binding.evaluate(now)
        if updates:
            self.emit_update(BindingValuePatch(updates))

    def idle_sleep(self) -> float:
        return self._FRAME_MS / 1000.0


__all__ = ["InlineBackend"]
