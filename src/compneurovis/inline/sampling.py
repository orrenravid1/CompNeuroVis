"""Runtime sampling helpers for generic callable-backed traces."""

from __future__ import annotations

from compneurovis.backends.base import BackendBase
from compneurovis.inline.widgets.line import TraceBinding


class TraceSampler:
    """Explicit sampler exposed to source step functions."""

    def __init__(self, traces: list[TraceBinding]) -> None:
        self._traces = traces

    def sample(self) -> None:
        for trace in self._traces:
            trace._sample()

    def _begin_update(self) -> None:
        for trace in self._traces:
            trace._begin_frame()


def emit_trace_updates(
    backend: BackendBase,
    traces: list[TraceBinding],
    *,
    auto_sample: bool = True,
) -> None:
    """Drain pending trace samples into backend field updates."""
    for trace in traces:
        if auto_sample and not trace._sampled_this_frame:
            trace._sample()
        message = trace._drain_message()
        if message is not None:
            backend.emit_update(message.payload)


__all__ = ["TraceSampler", "emit_trace_updates"]
