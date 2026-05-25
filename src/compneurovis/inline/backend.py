"""Runtime backend actors for inline-mode sources."""

from __future__ import annotations

from typing import Callable

from compneurovis.backends.base import BackendBase
from compneurovis.core.messages import InvokeAction, Message, MessagePayload, SetControl
from compneurovis.inline.bindings import ActionBinding, ControlBinding, TraceBinding, emit_trace_updates


class SourceStepContext:
    """Per-update context for sources that produce multiple samples per tick."""

    def __init__(self, traces: list[TraceBinding]) -> None:
        self._traces = traces

    def sample(self) -> None:
        for trace in self._traces:
            trace._sample()

    def _begin_update(self) -> None:
        for trace in self._traces:
            trace._begin_frame()


class InlineBackend(BackendBase):
    """Backend actor for pure-Python inline sources."""

    _FRAME_MS = 1000.0 / 60.0

    def __init__(
        self,
        *,
        traces: list[TraceBinding],
        controls: list[ControlBinding],
        actions: list[ActionBinding],
        step: Callable[[SourceStepContext], None] | None,
    ) -> None:
        super().__init__()
        self._traces = traces
        self._controls = controls
        self._actions = actions
        self._step_fn = step
        self._step_context = SourceStepContext(traces)
        self._done = False

    def handle(self, message: Message[MessagePayload]) -> None:
        payload = message.payload
        if isinstance(payload, SetControl):
            for control in self._controls:
                if control._control_id == payload.control_id:
                    control.apply(self, payload.value)
                    break
        elif isinstance(payload, InvokeAction):
            for action in self._actions:
                if action._action_id == payload.action_id:
                    action.fn()
                    if action.resets_fields:
                        for trace in self._traces:
                            self.emit_update(trace._replace_message().payload)
                    break

    def is_active(self) -> bool:
        return True

    def tick(self) -> None:
        if self._step_fn is not None and not self._done:
            self._step_context._begin_update()
            try:
                self._step_fn(self._step_context)
            except StopIteration:
                self._done = True
        emit_trace_updates(self, self._traces)

    def idle_sleep(self) -> float:
        return self._FRAME_MS / 1000.0


__all__ = ["InlineBackend", "SourceStepContext"]
