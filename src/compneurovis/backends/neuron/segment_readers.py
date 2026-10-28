"""Per-segment value producers for one NEURON geometry.

A producer answers "what is this quantity, for every visual segment?" — as a
whole array for a morphology display, or for one segment when a selection trace
samples it. Producers conform to `SegmentValueProducer`; a new kind is a class
that conforms, not another arm in a type ladder.

Compiled `PtrVector` readers are a property of the NEURON model and its
geometry, not of any view that displays them, so `SegmentValueReaders` owns them
on the backend: several morphologies over one geometry share a single reader per
quantity, and a quantity may be prepared before — or without — any view.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol, Sequence, runtime_checkable

import numpy as np

from compneurovis.core.runtime.performance import perf_log


@runtime_checkable
class SegmentValueProducer(Protocol):
    """One per-segment quantity, readable in bulk or one segment at a time."""

    def describe(self) -> str:
        """Short label for logs."""

    def is_prepared(self, readers: "SegmentValueReaders") -> bool:
        """Whether `read` would avoid compiling anything."""

    def prepare(self, backend: Any, readers: "SegmentValueReaders") -> bool:
        """Compile whatever `read` needs. True when reads avoid per-segment Python."""

    def read(self, backend: Any, readers: "SegmentValueReaders") -> np.ndarray:
        """One float32 value per visual segment, in geometry order."""

    def sample(
        self,
        backend: Any,
        readers: "SegmentValueReaders",
        seg: Any,
        index: int,
    ) -> float:
        """This quantity at one segment, given its visual index."""


def explicit_segment_values(
    values: Any, expected_count: int
) -> np.ndarray:
    resolved = np.asarray(values, dtype=np.float32).reshape(-1)
    if len(resolved) != expected_count:
        raise ValueError(
            "Explicit morphology data has "
            f"{len(resolved)} values; expected {expected_count} visual segments"
        )
    return resolved.copy()


class _PointerBackedValues:
    """Base for quantities NEURON can expose as one pointer per segment.

    Subclasses differ only in how a segment yields its pointer and its plain
    value; compilation, caching, bulk reads, and the sampled fallback are shared.
    """

    def describe(self) -> str:
        raise NotImplementedError

    def _cache_key(self) -> Any:
        raise NotImplementedError

    def _ref_for(self, seg: Any) -> Any:
        raise NotImplementedError

    def _value_for(self, seg: Any) -> float:
        raise NotImplementedError

    def is_prepared(self, readers: "SegmentValueReaders") -> bool:
        return readers.has_reader(self._cache_key())

    def prepare(self, backend: Any, readers: "SegmentValueReaders") -> bool:
        return self._reader(backend, readers) is not None

    def read(self, backend: Any, readers: "SegmentValueReaders") -> np.ndarray:
        reader = self._reader(backend, readers)
        if reader is None:
            return self._read_sampled(backend)
        ptr_vector, values_vector = reader
        ptr_vector.gather(values_vector)
        return np.asarray(values_vector.as_numpy(), dtype=np.float32).copy()

    def sample(
        self,
        backend: Any,
        readers: "SegmentValueReaders",
        seg: Any,
        index: int,
    ) -> float:
        del backend, readers, index
        return self._value_for(seg)

    def _reader(
        self, backend: Any, readers: "SegmentValueReaders"
    ) -> tuple[Any, Any] | None:
        return readers.compiled(
            backend,
            self._cache_key(),
            self._ref_for,
            self.describe(),
        )

    def _read_sampled(self, backend: Any) -> np.ndarray:
        sections_by_name = backend.sections_by_name()
        values = np.empty(len(backend.geometry.entity_ids), dtype=np.float32)
        for index, (section_name, xloc) in enumerate(
            zip(backend.geometry.section_names, backend.geometry.xlocs)
        ):
            seg = sections_by_name[str(section_name)](float(xloc))
            values[index] = self._value_for(seg)
        return values


@dataclass(frozen=True)
class RangeVariableValues(_PointerBackedValues):
    """A NEURON range variable, read as ``seg._ref_<variable>``."""

    variable: str

    def describe(self) -> str:
        return f"neuron:{self.variable}"

    def _cache_key(self) -> Any:
        return ("range", self.variable)

    def _ref_for(self, seg: Any) -> Any:
        return getattr(seg, f"_ref_{self.variable}", None)

    def _value_for(self, seg: Any) -> float:
        return float(getattr(seg, self.variable, np.nan))


@dataclass(frozen=True)
class SegmentRefValues(_PointerBackedValues):
    """An author callable mapping a segment to a NEURON ref, or to a value.

    When the callable returns a plain number there is no pointer to compile, so
    reads fall back to calling it once per segment.
    """

    ref_of: Callable[[Any], Any]

    def describe(self) -> str:
        return "callable"

    def _cache_key(self) -> Any:
        return ("ref_of", self.ref_of)

    def _ref_for(self, seg: Any) -> Any:
        return self.ref_of(seg)

    def _value_for(self, seg: Any) -> float:
        value = self.ref_of(seg)
        try:
            value = value[0]
        except (IndexError, TypeError):
            pass
        return float(value)


@dataclass(frozen=True, eq=False)
class ExplicitSegmentValues:
    """One value per visual segment, supplied and owned by the app."""

    values: Sequence[float] | np.ndarray

    def describe(self) -> str:
        return "explicit-values"

    def is_prepared(self, readers: "SegmentValueReaders") -> bool:
        del readers
        return True

    def prepare(self, backend: Any, readers: "SegmentValueReaders") -> bool:
        del backend, readers
        return True

    def read(self, backend: Any, readers: "SegmentValueReaders") -> np.ndarray:
        del readers
        return explicit_segment_values(
            self.values, len(backend.geometry.entity_ids)
        )

    def sample(
        self,
        backend: Any,
        readers: "SegmentValueReaders",
        seg: Any,
        index: int,
    ) -> float:
        del backend, readers, seg
        return float(np.asarray(self.values).reshape(-1)[index])


@dataclass(frozen=True, eq=False)
class DerivedSegmentValues:
    """An elementwise function of other per-segment quantities.

    ``fn`` runs on whole arrays for a display read and on plain floats when a
    selection trace samples one segment, so it must be elementwise arithmetic
    rather than anything that inspects shape or length.
    """

    inputs: tuple[SegmentValueProducer, ...]
    fn: Callable[..., Any]
    name: str = "derived"

    def describe(self) -> str:
        return f"{self.name}({', '.join(i.describe() for i in self.inputs)})"

    def is_prepared(self, readers: "SegmentValueReaders") -> bool:
        return all(item.is_prepared(readers) for item in self.inputs)

    def prepare(self, backend: Any, readers: "SegmentValueReaders") -> bool:
        # Prepare every input, then report; do not short-circuit on the first
        # non-vectorized one or the rest never get compiled.
        return all([item.prepare(backend, readers) for item in self.inputs])

    def read(self, backend: Any, readers: "SegmentValueReaders") -> np.ndarray:
        arrays = [item.read(backend, readers) for item in self.inputs]
        values = np.asarray(self.fn(*arrays), dtype=np.float32).reshape(-1)
        expected = len(backend.geometry.entity_ids)
        if len(values) != expected:
            raise ValueError(
                f"Derived source {self.describe()} produced {len(values)} "
                f"values; expected {expected} visual segments"
            )
        return values

    def sample(
        self,
        backend: Any,
        readers: "SegmentValueReaders",
        seg: Any,
        index: int,
    ) -> float:
        return float(
            self.fn(
                *(
                    item.sample(backend, readers, seg, index)
                    for item in self.inputs
                )
            )
        )


#: What an author may hand to a morphology or a recorder as one quantity.
SegmentValueSource = (
    str
    | Callable[[Any], Any]
    | Sequence[float]
    | np.ndarray
    | SegmentValueProducer
)


def as_producer(source: SegmentValueSource) -> SegmentValueProducer:
    """Lift an authored source into the producer contract.

    This is the one boundary where a plain string, callable, or array becomes a
    producer. Anything already conforming passes through untouched, so a new
    kind needs no change here.
    """

    if isinstance(source, SegmentValueProducer):
        return source
    if isinstance(source, str):
        return RangeVariableValues(source)
    if callable(source):
        return SegmentRefValues(source)
    return ExplicitSegmentValues(source)


def describe_segment_source(source: SegmentValueSource) -> str:
    return as_producer(source).describe()


class SegmentValueReaders:
    """Backend-owned cache of compiled per-segment readers.

    Compiling one costs a pointer lookup per visual segment, so it is memoized
    for the backend's lifetime under a key the producer chooses — never under
    ``id()``, which a later object may reuse. ``None`` records a quantity with
    no native pointer, which must be sampled segment by segment.
    """

    def __init__(self) -> None:
        self._readers: dict[Any, tuple[Any, Any] | None] = {}

    def is_prepared(self, source: SegmentValueSource) -> bool:
        return as_producer(source).is_prepared(self)

    def prepare(self, backend: Any, source: SegmentValueSource) -> bool:
        return as_producer(source).prepare(backend, self)

    def read(self, backend: Any, source: SegmentValueSource) -> np.ndarray:
        return as_producer(source).read(backend, self)

    def sample(
        self,
        backend: Any,
        source: SegmentValueSource,
        seg: Any,
        index: int,
    ) -> float:
        return as_producer(source).sample(backend, self, seg, index)

    def has_reader(self, key: Any) -> bool:
        return key in self._readers

    def compiled(
        self,
        backend: Any,
        key: Any,
        ref_of: Callable[[Any], Any],
        description: str,
    ) -> tuple[Any, Any] | None:
        if key not in self._readers:
            self._readers[key] = self._build(backend, ref_of, description)
        return self._readers[key]

    @staticmethod
    def _build(
        backend: Any, ref_of: Callable[[Any], Any], description: str
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
            ref = ref_of(seg)
            if ref is None or isinstance(ref, (int, float, np.number)):
                return None
            try:
                ptr_vector.pset(index, ref)
            except (TypeError, ValueError, RuntimeError):
                return None
        perf_log(
            "neuron_segment_readers",
            "reader_built",
            source=description,
            segment_count=count,
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )
        return ptr_vector, values_vector


__all__ = [
    "DerivedSegmentValues",
    "ExplicitSegmentValues",
    "RangeVariableValues",
    "SegmentRefValues",
    "SegmentValueProducer",
    "SegmentValueReaders",
    "SegmentValueSource",
    "as_producer",
    "describe_segment_source",
    "explicit_segment_values",
]
