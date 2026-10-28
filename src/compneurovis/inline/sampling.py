"""Runtime sampling helpers for generic callable-backed series."""

from __future__ import annotations

from compneurovis.backends.base import BackendBase
from compneurovis.inline.data_producers import SeriesProducer


class SeriesSampler:
    """Explicit sampler exposed to source step functions."""

    def __init__(self, series: list[SeriesProducer]) -> None:
        self._series = series

    def sample(self) -> None:
        for trace in self._series:
            trace._sample()

    def _begin_update(self) -> None:
        for trace in self._series:
            trace._begin_frame()


def emit_series_updates(
    backend: BackendBase,
    series: list[SeriesProducer],
    *,
    auto_sample: bool = True,
) -> None:
    """Drain pending trace samples into backend field updates."""
    for trace in series:
        if auto_sample and not trace._sampled_this_frame:
            trace._sample()
        message = trace._drain_message()
        if message is not None:
            backend.emit_update(message.payload)


__all__ = ["SeriesSampler", "emit_series_updates"]
