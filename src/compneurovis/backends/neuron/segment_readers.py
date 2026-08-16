"""Compiled per-segment value readers for one NEURON geometry.

A reader is a property of the NEURON model and its visual geometry, not of any
view that happens to display it. Several morphologies over one geometry share a
single compiled ``PtrVector`` per source, and a source can be prepared before —
or without — any morphology exists to show it.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Sequence

import numpy as np

from compneurovis.core.runtime.performance import perf_log

SegmentValueSource = str | Callable[[Any], Any] | Sequence[float] | np.ndarray


def is_explicit_segment_values(source: SegmentValueSource) -> bool:
    """Whether this source already carries one value per visual segment."""

    return not isinstance(source, str) and not callable(source)


def explicit_segment_values(
    source: SegmentValueSource, expected_count: int
) -> np.ndarray:
    values = np.asarray(source, dtype=np.float32).reshape(-1)
    if len(values) != expected_count:
        raise ValueError(
            "Explicit morphology data has "
            f"{len(values)} values; expected {expected_count} visual segments"
        )
    return values.copy()


class SegmentValueReaders:
    """Compiles and caches one native reader per per-segment value source.

    Compiling a reader costs one pointer lookup per visual segment, so it is
    cached for the backend's lifetime and keyed by the source object itself —
    never by ``id()``, which a later object may reuse. ``None`` records a source
    that has no native reader and must be sampled segment by segment.
    """

    def __init__(self) -> None:
        self._readers: dict[Any, tuple[Any, Any] | None] = {}

    def is_prepared(self, source: SegmentValueSource) -> bool:
        return is_explicit_segment_values(source) or source in self._readers

    def prepare(self, backend: Any, source: SegmentValueSource) -> bool:
        """Compile this source's reader now. True when it reads natively."""

        if is_explicit_segment_values(source):
            return False
        if source not in self._readers:
            self._readers[source] = self._build(backend, source)
        return self._readers[source] is not None

    def read(self, backend: Any, source: SegmentValueSource) -> np.ndarray:
        if is_explicit_segment_values(source):
            return explicit_segment_values(
                source, len(backend.geometry.entity_ids)
            )
        if source not in self._readers:
            self._readers[source] = self._build(backend, source)
        reader = self._readers[source]
        if reader is None:
            return self._read_sampled(backend, source)
        ptr_vector, values_vector = reader
        ptr_vector.gather(values_vector)
        return np.asarray(values_vector.as_numpy(), dtype=np.float32).copy()

    def _build(
        self, backend: Any, source: SegmentValueSource
    ) -> tuple[Any, Any] | None:
        from neuron import h

        started = time.monotonic()
        count = len(backend.geometry.entity_ids)
        sections_by_name = backend.sections_by_name()
        ptr_vector = h.PtrVector(count)
        values_vector = h.Vector(count)
        for index, (section_name, xloc) in enumerate(
            zip(backend.geometry.section_names, backend.geometry.xlocs)
        ):
            seg = sections_by_name[str(section_name)](float(xloc))
            ref = (
                source(seg)
                if callable(source)
                else getattr(seg, f"_ref_{source}", None)
            )
            if ref is None or isinstance(ref, (int, float, np.number)):
                return None
            try:
                ptr_vector.pset(index, ref)
            except (TypeError, ValueError, RuntimeError):
                return None
        perf_log(
            "neuron_segment_readers",
            "reader_built",
            source=describe_segment_source(source),
            segment_count=count,
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )
        return ptr_vector, values_vector

    @staticmethod
    def _read_sampled(backend: Any, source: SegmentValueSource) -> np.ndarray:
        sections_by_name = backend.sections_by_name()
        values = np.empty(len(backend.geometry.entity_ids), dtype=np.float32)
        for index, (section_name, xloc) in enumerate(
            zip(backend.geometry.section_names, backend.geometry.xlocs)
        ):
            seg = sections_by_name[str(section_name)](float(xloc))
            if callable(source):
                value = source(seg)
                try:
                    value = value[0]
                except (IndexError, TypeError):
                    pass
            else:
                value = getattr(seg, source, np.nan)
            values[index] = float(value)
        return values


def describe_segment_source(source: SegmentValueSource) -> str:
    if isinstance(source, str):
        return f"neuron:{source}"
    if callable(source):
        return "callable"
    return "explicit-values"


__all__ = [
    "SegmentValueReaders",
    "SegmentValueSource",
    "describe_segment_source",
    "explicit_segment_values",
    "is_explicit_segment_values",
]
