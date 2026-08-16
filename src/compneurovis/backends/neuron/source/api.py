"""Inline-mode source API for NEURON backends.

``source(sections=[...])`` wraps an existing NEURON model without subclassing
``NeuronBackend``. Shared widgets are inherited from
:class:`NeuronInlineSource`; this module adds only the source-specific runtime
and optimized NEURON data producers.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

import numpy as np

from compneurovis.backends.neuron.backend import NeuronBackend
from compneurovis.backends.neuron.source.declarations import (
    NeuronInlineSource,
    _coerce_series_initial,
    _time_coord,
)
from compneurovis.core.field import FieldSpec
from compneurovis.inline._ids import slug
from compneurovis.inline.refs import DataRef
from compneurovis.backends.neuron.source.recording import (
    NeuronRefRecorder,
    SegmentVariableHistoryBinding,
    _resolve_ref_record_max_samples,
)
from compneurovis.backends.neuron.source.runtime import SourceBackend


class NeuronSource(NeuronInlineSource):
    """NEURON source returned by `cnv.neuron.source()`.

    Construct through the factory so NEURON integration defaults are resolved
    consistently. The source remains panel-free until view methods are called.
    """

    def __init__(
        self,
        *,
        sections: list,
        step: Callable[[], None] | None,
        dt: float,
        display_dt: float | None,
        flush_dt: float | None,
        v_init: float,
        title: str = "CompNeuroVis",
    ) -> None:
        super().__init__(title=title)
        self._sections = sections
        self._step_fn = step
        self._dt = dt
        self._display_dt = display_dt
        self._flush_dt = flush_dt
        self._v_init = v_init

    def record_selection(
        self,
        name: str,
        *,
        selection: DataRef,
        variables: Mapping[str, str],
        unit: str = "",
        max_samples: int = 5000,
    ) -> DataRef:
        """Record NEURON variables from the currently selected segment.

        This method is NEURON-specific data plumbing. The returned handle can
        feed any compatible widget, including the shared ``line()`` method.
        """
        selection_binding = (
            selection._selectors.get("segment")
            if isinstance(selection, DataRef)
            else None
        )
        if (
            not isinstance(selection, DataRef)
            or selection._series_dim != "segment"
            or selection_binding is None
            or selection_binding.key not in self._morphology_selection_ids
        ):
            raise ValueError("record_selection(...) expects morphology_handle.selection")
        binding = SegmentVariableHistoryBinding(
            name=name,
            variables=dict(variables),
            selection_id=selection_binding.key,
            unit=unit,
            max_samples=max_samples,
        )
        binding._register(len(self._segment_variable_histories))
        self._segment_variable_histories.append(binding)
        self._add_widget(field_builders=(binding._initial_field,))
        return DataRef(
            _field_id=binding._field_id,
            _series_dim="variable",
            _selectors=dict(selection._selectors),
            _unit=unit,
        )

    def record_refs(
        self,
        name: str,
        *,
        refs: Sequence[Any],
        series: Sequence[str],
        field_id: str | None = None,
        max_samples: int | None = None,
        sample_dt: float | None = None,
        window: float | None = None,
        unit: str | None = None,
        by: str | None = None,
        initial: Sequence[float] | np.ndarray | None = None,
    ) -> DataRef:
        """Create an optimized time-series source from NEURON references.

        Args:
            name: Stable source name.
            refs: NEURON references sampled through `PtrVector`.
            series: Label corresponding to each reference.
            field_id: Advanced explicit data identifier.
            max_samples: Maximum retained samples. When omitted, it is inferred
                from `window` and the sample interval.
            sample_dt: Simulation-time interval between retained samples.
            window: Rolling history duration in milliseconds.
            unit: Unit shared by all series.
            by: Name of the series dimension.
            initial: Optional initial values instead of immediately reading refs.

        Returns:
            An optimized data source for `line(source=...)`.

        This method declares data only; no panel appears until `line()` is
        called.
        """
        labels = tuple(str(item) for item in series)
        ref_tuple = tuple(refs)
        if not labels:
            raise ValueError("record_refs(...) requires at least one series label")
        if len(ref_tuple) != len(labels):
            raise ValueError("record_refs(...) refs and series must have the same length")

        series_dim = by or "series"
        resolved_field_id = field_id or f"{slug(name)}_field"
        resolved_sample_dt = self._display_dt if sample_dt is None else sample_dt
        resolved_max_samples = _resolve_ref_record_max_samples(
            explicit=max_samples,
            rolling_window=window,
            sample_dt=resolved_sample_dt,
            sim_dt=self._dt,
        )
        recorder = NeuronRefRecorder(
            field_id=resolved_field_id,
            series_dim=series_dim,
            series=labels,
            refs=ref_tuple,
            max_samples=resolved_max_samples,
            sample_dt=resolved_sample_dt,
        )

        def build_field(backend: NeuronBackend) -> FieldSpec:
            raw: Any = initial if initial is not None else recorder.sample_vector()
            values = _coerce_series_initial(raw, len(labels))
            time_coord = _time_coord(backend)
            recorder.mark_emitted(float(time_coord[-1]))
            return FieldSpec(
                id=resolved_field_id,
                initial_values=values,
                dims=(series_dim, "time"),
                coords={series_dim: np.asarray(labels), "time": time_coord},
                unit=unit,
            )

        self._recorders.append(recorder)
        self._add_widget(field_builders=(build_field,))
        return DataRef(
            _field_id=resolved_field_id,
            _series_dim=series_dim,
            _selectors={},
            _unit=unit,
        )

    def _make_backend(self) -> SourceBackend:
        return SourceBackend(
            sections=self._sections,
            controls=self._control_bindings,
            actions=self._actions,
            series=self._series,
            fields=self._fields,
            segment_variable_displays=self._segment_variable_displays,
            segment_variable_histories=self._segment_variable_histories,
            recorders=self._recorders,
            click_handlers=self._click_handlers,
            pointer_handlers=self._pointer_interaction_handlers,
            capture_predicate=self._capture_predicate,
            initial_state=self._initial_values,
            derives=self._derives,
            step_fn=self._step_fn,
            dt=self._dt,
            display_dt=self._display_dt,
            flush_dt=self._flush_dt,
            v_init=self._v_init,
            title=self._app_title or self.title,
        )


def source(
    *,
    sections: Sequence,
    step: Callable[[], None] | None = None,
    dt: float | None = None,
    display_dt: float | None = 0.1,
    flush_dt: float | None = None,
    v_init: float = -65.0,
    title: str = "CompNeuroVis",
) -> NeuronSource:
    """Create a CompNeuroVis NEURON source for an existing model.

    Args:
        sections: Existing NEURON sections owned by the model.
        step: Optional no-argument model step. When omitted, CompNeuroVis calls
            `h.fadvance()`.
        dt: Integration step in milliseconds. Defaults to current `h.dt`.
        display_dt: Simulation-time interval between display samples.
        flush_dt: Simulation-time interval between frontend update batches.
            `None` or zero flushes every sampled tick.
        v_init: Initialization voltage in millivolts.
        title: Fallback window title. `cnv.show(title=...)` overrides it.

    Returns:
        A bare NEURON source. Views remain opt-in.

    ``flush_dt`` (sim-ms) decouples frontend updates from the sim tick: the model
    advances + samples every tick, but display/history/recorder updates are
    coalesced and flushed at most every ``flush_dt`` sim-ms. ``None``/0 flushes
    every tick (original behavior). Raise it (e.g. 10–50) to cut the message rate
    the frontend must process, without slowing the sim or thinning the trace.
    """

    from neuron import h

    resolved_dt = float(dt) if dt is not None else float(h.dt)
    source = NeuronSource(
        sections=list(sections),
        step=step,
        dt=resolved_dt,
        display_dt=display_dt,
        flush_dt=flush_dt,
        v_init=v_init,
        title=title,
    )
    from compneurovis.inline.authoring import _register_current_source

    _register_current_source(source)
    return source


__all__ = [
    "NeuronSource",
    "NeuronRefRecorder",
    "source",
]
