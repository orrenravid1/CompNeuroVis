"""Shared inline-authoring composition layer for NEURON sources.

``NeuronSource`` wraps raw sections and declares views and panels over the
fields their backend emits. That vocabulary -- ``morphology``, ``history``,
``line``, ``network2d``, ``controls``, ``layout`` -- is backend-agnostic and
lives here once so AppSpec composition stays separate from source-specific
runtime sampling.
"""

from __future__ import annotations

import bisect
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from compneurovis.backends.neuron.backend import NeuronBackend
from compneurovis.backends.neuron.segment_readers import (
    DerivedSegmentValues,
    as_producer,
)
from compneurovis.backends.neuron.source.recording import (
    SegmentValueSource,
    SegmentVariableDisplayBinding,
    SegmentVariableDisplayRef,
    SegmentVariableHistoryBinding,
)
from compneurovis.core.field import FieldSpec
from compneurovis.core.values import ValueBindingSpec
from compneurovis.inline._ids import slug
from compneurovis.inline.refs import (
    DataRef,
    GeometryRef,
    MorphologyRef,
    SelectionRef,
    ValueRef,
)
from compneurovis.inline.sources import InlineSourceBase
from compneurovis.inline.interactions import EntityClickHandler
from compneurovis.components.morphology.authoring import (
    DEFAULT_MORPHOLOGY_CAMERA_ORBIT_SENSITIVITY,
    DEFAULT_MORPHOLOGY_CAMERA_PAN_SENSITIVITY,
    DEFAULT_MORPHOLOGY_CAMERA_ZOOM_SENSITIVITY,
)
from compneurovis.backends.neuron.section_names import public_section_name

ClickHandler = EntityClickHandler
SampleFn = Callable[[], Any]
_MISSING = object()


def _public_morphology_selection(selected: Any) -> Any:
    """Normalize only importer-owned section prefixes in authored entity ids."""
    if selected is None:
        return None

    def normalize(entity_id: Any) -> str:
        value = str(entity_id)
        section_name, separator, xloc = value.rpartition("@")
        if not separator:
            return value
        return f"{public_section_name(section_name)}@{xloc}"

    if isinstance(selected, (str, bytes)):
        return normalize(selected)
    try:
        return tuple(normalize(entity_id) for entity_id in selected)
    except TypeError:
        return normalize(selected)



def _time_coord(backend: NeuronBackend) -> np.ndarray:
    value = getattr(backend, "_last_time_value", None)
    return np.asarray([0.0 if value is None else float(value)], dtype=np.float32)


def _coerce_series_initial(values: Any, series_count: int) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float32)
    if arr.ndim == 0:
        arr = arr.reshape(1, 1)
    elif arr.ndim == 1:
        arr = arr.reshape(arr.shape[0], 1)
    if arr.shape[0] != series_count:
        raise ValueError(f"Initial line values have {arr.shape[0]} series, expected {series_count}")
    return arr




@dataclass
class LineRecorder:
    """Per-tick sampler feeding a declared ``line(...)`` field.

    The source backend calls ``sample()`` once per integration step, stacks the
    batch, and appends it to ``field_id`` along ``series_dim``/time. ``sample``
    returns one value per series (array-like of length ``len(series)``).
    """

    field_id: str
    series_dim: str
    series: tuple[str, ...]
    sample: SampleFn
    max_samples: int = 5000

    def sample_vector(self) -> np.ndarray:
        return np.asarray(self.sample(), dtype=np.float32).reshape(len(self.series))


@dataclass
class DerivedField:
    """A value computed from the live sim each frame.

    Sampling and evaluation are split for performance: when ``over`` is set, the
    backend appends ``over()`` to a rolling ``window`` (ms) every frame — cheap —
    and calls ``fn(t, v)`` only when ``max_refresh_hz`` is due. With no ``over``,
    ``fn()`` returns the current value(s) directly. ``target="field"`` emits a
    field (append: a time series; replace: a snapshot vector); ``target="value"``
    publishes one runtime value under ``name``.
    """

    name: str
    fn: Callable[..., Any]
    target: str  # "field" | "value"
    field_id: str
    series: tuple[str, ...]
    series_dim: str
    mode: str  # "append" | "replace"
    over: SampleFn | None
    window: float
    max_refresh_hz: float | None
    max_samples: int = 5000
    _times: list[float] = field(default_factory=list)
    _values: list[np.ndarray] = field(default_factory=list)
    _last_eval_s: float = field(default=float("-inf"))

    def observe(self, t: float) -> None:
        if self.over is None:
            return
        self._times.append(float(t))
        self._values.append(np.asarray(self.over(), dtype=np.float64).copy())
        if self._times[0] < self._times[-1] - self.window:
            cut = bisect.bisect_left(self._times, self._times[-1] - self.window)
            if cut > 0:
                del self._times[:cut]
                del self._values[:cut]

    def due(self, now: float) -> bool:
        interval = (1.0 / self.max_refresh_hz) if self.max_refresh_hz and self.max_refresh_hz > 0 else 0.0
        return (now - self._last_eval_s) >= interval

    def evaluate(self, now: float) -> Any:
        if self.over is not None:
            if len(self._times) < 2:
                return None
            self._last_eval_s = now
            return self.fn(
                np.asarray(self._times, dtype=np.float64),
                np.asarray(self._values, dtype=np.float64),
            )
        self._last_eval_s = now
        return self.fn()

    def field_values(self, result: Any) -> np.ndarray:
        return np.asarray(result, dtype=np.float32).reshape(len(self.series))

    def reset(self) -> None:
        self._times.clear()
        self._values.clear()
        self._last_eval_s = float("-inf")


class NeuronInlineSource(InlineSourceBase):
    """Shared composition vocabulary for NEURON inline sources.

    Subclasses provide ``_make_backend``; everything below -- view/panel
    declaration and AppSpec assembly -- is shared by source-owned source
    variants.
    """

    def __init__(self, *, title: str = "CompNeuroVis") -> None:
        super().__init__(title=title)
        # Runtime hooks, executed by the source-owned backend.
        self._recorders: list[LineRecorder] = []
        self._capture_predicate: ClickHandler | None = None
        self._derives: list[DerivedField] = []
        self._segment_variable_displays: list[SegmentVariableDisplayBinding] = []
        self._segment_variable_histories: list[SegmentVariableHistoryBinding] = []
        self._prepared_segment_sources: list[SegmentValueSource] = []
        self._morphology_selection_ids: set[str] = set()

    # -- authoring vocabulary -------------------------------------------------

    def derived_segment_values(
        self,
        *sources: SegmentValueSource,
        fn: Callable[..., Any],
        name: str = "derived",
    ) -> DerivedSegmentValues:
        """Combine per-segment quantities with an elementwise function.

        The result is an ordinary per-segment source: hand it to
        `morphology(variable=...)`, `set_display(data=...)`, or
        `prepare_segment_values(...)` like any other. Inputs are read from their
        own compiled readers and combined with NumPy, so a derived quantity
        costs one array expression per frame rather than a Python call per
        segment.

        Args:
            *sources: The input quantities, in the order `fn` receives them.
            fn: Elementwise function. It runs on whole arrays for a display and
                on plain floats when a selection trace samples one segment, so
                it must not inspect shape or length.
            name: Label used in logs.

        Returns:
            A per-segment source combining those inputs.
        """
        if not sources:
            raise ValueError("derived_segment_values(...) needs at least one source")
        return DerivedSegmentValues(
            inputs=tuple(as_producer(source) for source in sources),
            fn=fn,
            name=name,
        )

    def prepare_segment_values(self, *sources: SegmentValueSource) -> None:
        """Compile native readers for these per-segment sources at startup.

        Reading one source costs a pointer lookup per visual segment the first
        time it is used, which on a large model stalls whichever callback asks
        for it first. Declaring a source here moves that cost into startup
        instead. Readers belong to the backend, so this neither names nor
        requires a morphology: prepare a source before, or without, any view
        that displays it.

        Args:
            *sources: NEURON range-variable names or `seg -> ref` callables.
                Explicit per-segment values need no reader and are ignored.
        """
        for source in sources:
            self._prepared_segment_sources.append(source)

    def morphology(
        self,
        *,
        variable: SegmentValueSource,
        name: str = "Morphology",
        unit: str | None = None,
        color_limits: tuple[float, float] | None = None,
        color_map: str = "scalar",
        color_norm: str = "auto",
        color_field_id: str | None = None,
        background_color: Any = "white",
        max_refresh_hz: float | None = None,
        camera_orbit_sensitivity: float = DEFAULT_MORPHOLOGY_CAMERA_ORBIT_SENSITIVITY,
        camera_pan_sensitivity: float = DEFAULT_MORPHOLOGY_CAMERA_PAN_SENSITIVITY,
        camera_zoom_sensitivity: float = DEFAULT_MORPHOLOGY_CAMERA_ZOOM_SENSITIVITY,
        selected: Any = None,
        selectable: bool = True,
        select_multiple: bool = False,
        panel: bool = True,
    ) -> MorphologyRef:
        """Render a per-segment scalar over the morphology.

        ``variable`` is a NEURON range-variable name (read as ``seg._ref_<var>``),
        a callable ``seg -> ref/value``, or one explicit value per visual segment.
        It is always one current data source, with no privileged default. Voltage
        is just ``morphology(variable="v", unit="mV", ...)``.

        ``selectable=False`` makes the panel visual-only: clicks do not emit
        entity selection. ``selected`` initializes the selection: pass one entity
        id for single-select, or an iterable of ids when ``select_multiple=True``.
        ``None`` or an empty iterable means no selected trace. Internally the
        selection is always stored as a list, and the returned handle's
        ``.selection`` is a :class:`DataRef` over that list.

        ``panel=False`` declares the display variable + selection source but adds
        no 3D panel (no canvas). Useful for headless/sweep contexts, or to isolate
        the 3D-draw cost while keeping the same backend data stream.
        """
        if select_multiple and not selectable:
            raise ValueError("morphology(select_multiple=True) requires selectable=True")
        selected = _public_morphology_selection(selected)

        display_binding = next(
            (
                binding
                for binding in self._segment_variable_displays
                if binding._field_id == color_field_id
            ),
            None,
        )
        display_ref = (
            SegmentVariableDisplayRef(display_binding)
            if display_binding is not None
            else None
        )
        if color_field_id is None:
            variable_name = (
                str(variable)
                if isinstance(variable, str)
                else getattr(variable, "__name__", "value")
            )
            display_ref = self._segment_variable_display(
                f"{name} color",
                variable=variable_name,
                source=variable,
                unit=unit,
                color_limits=color_limits,
                color_map=color_map,
            )
            color_field_id = display_ref.field_id
            display_binding = display_ref._binding

        morphology = super().morphology(
            GeometryRef("morphology", "morphology"),
            name=name,
            color=DataRef(_field_id=color_field_id),
            selected=selected,
            select_multiple=select_multiple,
            selectable=selectable,
            panel=panel,
            color_map=color_map,
            # The live field owns the one current limits/palette state. Keeping
            # the view unset lets each FieldReplace carry an atomic retarget.
            color_limits=None,
            color_norm=color_norm,
            background_color=background_color,
            max_refresh_hz=max_refresh_hz,
            camera_orbit_sensitivity=camera_orbit_sensitivity,
            camera_pan_sensitivity=camera_pan_sensitivity,
            camera_zoom_sensitivity=camera_zoom_sensitivity,
        )
        selection_data = None
        if selectable:
            # The trace follows this morphology's display, so it declares no
            # variables of its own: retargeting the display retargets the trace.
            history = SegmentVariableHistoryBinding(
                name=f"{name} selection",
                selection_id=morphology.selected.id,
                unit=unit or "",
                display_binding=display_binding,
                include_variable_dim=False,
            )
            history._register(len(self._segment_variable_histories))
            self._segment_variable_histories.append(history)
            self._morphology_selection_ids.add(morphology.selected.id)
            self._add_widget(field_builders=(history._initial_field,))
            selection_data = DataRef(
                _field_id=history._field_id,
                _series_dim="segment",
                _selectors={
                    "segment": ValueBindingSpec(morphology.selected.id)
                },
                _unit=unit,
            )
        return MorphologyRef(
            id=morphology.id,
            geometry=morphology.geometry,
            color=morphology.color,
            selection=selection_data,
            selected=morphology.selected,
            entity_click=morphology.entity_click,
            _display=display_ref,
        )

    def _segment_variable_display(
        self,
        name: str,
        *,
        variable: str,
        source: SegmentValueSource,
        unit: str | None = None,
        color_limits: tuple[float, float] | None = None,
        color_map: str = "scalar",
    ) -> SegmentVariableDisplayRef:
        binding = SegmentVariableDisplayBinding(
            name=name,
            variable=variable,
            source=source,
            unit=unit,
            color_limits=color_limits,
            color_map=color_map,
        )
        binding._register(len(self._segment_variable_displays))
        self._segment_variable_displays.append(binding)
        self._add_widget(field_builders=(binding._initial_field,))
        return SegmentVariableDisplayRef(binding)

    def record(
        self,
        name: str,
        *,
        sample: SampleFn | None = None,
        series: Sequence[str],
        initial: Callable[[NeuronBackend], Any] | Sequence[float] | np.ndarray | None = None,
        field_id: str | None = None,
        max_samples: int = 5000,
        unit: str | None = None,
        by: str | None = None,
    ) -> DataRef:
        """Create a NEURON-sampled time-series field.

        Args:
            name: Stable source name.
            sample: No-argument callable returning one value per series.
            series: Labels defining returned-value order.
            initial: Initial values or a callable receiving the backend.
            field_id: Advanced explicit data identifier.
            max_samples: Maximum retained samples.
            unit: Unit shared by all series.
            by: Name of the series dimension.

        Returns:
            A data source for `line(source=...)`.

        This is data plumbing only. Plot it with ``line(source=...)`` so the
        widget stays backend-agnostic.
        """
        labels = tuple(str(item) for item in series)
        if not labels:
            raise ValueError("record(...) requires at least one series label")
        if sample is None and initial is None:
            raise ValueError("record(...) requires sample=... or initial=...")

        series_dim = by or "series"
        resolved_field_id = field_id or f"{slug(name)}_field"

        def build_field(backend: NeuronBackend) -> FieldSpec:
            if initial is not None:
                raw: Any = initial(backend) if callable(initial) else initial
            elif sample is not None:
                raw = sample()
            else:
                raw = np.zeros((len(labels), 1), dtype=np.float32)
            values = _coerce_series_initial(raw, len(labels))
            return FieldSpec(
                id=resolved_field_id,
                initial_values=values,
                dims=(series_dim, "time"),
                coords={series_dim: np.asarray(labels), "time": _time_coord(backend)},
                unit=unit,
            )

        if sample is not None:
            self._recorders.append(
                LineRecorder(
                    field_id=resolved_field_id,
                    series_dim=series_dim,
                    series=labels,
                    sample=sample,
                    max_samples=max_samples,
                )
            )
        self._add_widget(field_builders=(build_field,))
        return DataRef(
            _field_id=resolved_field_id,
            _series_dim=series_dim,
            _selectors={},
            _unit=unit,
        )

    def interactions(
        self,
        *,
        entity_click: ClickHandler | None = None,
        capture_series: ClickHandler | None = None,
    ) -> None:
        """Register advanced NEURON interaction callbacks.

        Args:
            entity_click: Called as `entity_click(ctx, entity_id)` before an
                authored click's optional default selection behavior. Return
                truthy to consume the click without that default mutation.
            capture_series: Called as `capture_series(ctx, entity_id)` before
                selected-segment history changes. Return whether to capture.

        Normal controls and actions should use typed control methods,
        `button()`, and `hotkey()` instead.
        """

        if entity_click is None and capture_series is None:
            raise ValueError("interactions(...) requires at least one handler")
        if entity_click is not None:
            super().interactions(entity_click=entity_click)
        if capture_series is not None:
            self._capture_predicate = capture_series

    def derive(
        self,
        name: str,
        fn: Callable[..., Any],
        *,
        over: SampleFn | None = None,
        window: float = 2000.0,
        series: Sequence[str] | None = None,
        by: str | None = None,
        mode: str = "append",
        max_refresh_hz: float | None = 10.0,
        max_samples: int = 5000,
        unit: str | None = None,
    ) -> DataRef:
        """Compute a field from the live sim.

        Args:
            name: Stable derived-data name.
            fn: Metric callable. It receives no arguments without `over`,
                or `(times, values)` when a signal window is supplied.
            over: Optional no-argument signal sampler.
            window: Buffered signal duration in milliseconds.
            series: Labels defining returned-value order.
            by: Name of the series dimension.
            mode: `"append"` for time history or `"replace"` for current
                values.
            max_refresh_hz: Maximum metric evaluation frequency.
            max_samples: Maximum retained samples in append mode.
            unit: Unit shared by returned values.

        Returns:
            A data source for `line(source=...)` or `bar(source=...)`.

        ``fn`` is your metric/classifier. With ``over=<signal>`` the backend
        buffers ``window`` ms of that signal and calls ``fn(t, v)``; otherwise
        ``fn()`` returns the current value(s). Returns a :class:`DataRef` to
        feed ``line(source=...)``/``bar(source=...)``. Evaluation is throttled by
        ``max_refresh_hz`` independently of sampling.
        """
        if mode not in ("append", "replace"):
            raise ValueError("derive(mode=...) must be 'append' or 'replace'")

        labels = tuple(str(item) for item in (series if series is not None else (name,)))
        series_dim = by or "series"
        field_id = f"{slug(name)}_field"
        self._derives.append(
            DerivedField(
                name=name, fn=fn, target="field", field_id=field_id, series=labels,
                series_dim=series_dim, mode=mode, over=over, window=window,
                max_refresh_hz=max_refresh_hz, max_samples=max_samples,
            )
        )

        def build_field(backend: NeuronBackend) -> FieldSpec:
            raw: Any = None
            if over is None:
                try:
                    raw = np.asarray(fn(), dtype=np.float32).reshape(len(labels))
                except Exception:
                    raw = None
            base = np.zeros(len(labels), dtype=np.float32) if raw is None else raw
            if mode == "append":
                return FieldSpec(
                    id=field_id,
                    initial_values=base.reshape(len(labels), 1),
                    dims=(series_dim, "time"),
                    coords={series_dim: np.asarray(labels), "time": _time_coord(backend)},
                    unit=unit,
                )
            return FieldSpec(
                id=field_id,
                initial_values=base,
                dims=(series_dim,),
                coords={series_dim: np.asarray(labels)},
                unit=unit,
            )

        self._add_widget(field_builders=(build_field,))
        return DataRef(
            _field_id=field_id,
            _series_dim=series_dim,
            _selectors={},
            _unit=unit,
        )

    def derive_value(
        self,
        name: str,
        fn: Callable[..., Any],
        *,
        over: SampleFn | None = None,
        window: float = 2000.0,
        max_refresh_hz: float | None = 10.0,
        initial: Any = _MISSING,
    ) -> ValueRef:
        """Compute one runtime value from the live NEURON simulation.

        Args:
            name: Stable value name.
            fn: Metric callable. It receives no arguments without `over`,
                or `(times, values)` when a signal window is supplied.
            over: Optional no-argument signal sampler.
            window: Buffered signal duration in milliseconds.
            max_refresh_hz: Maximum metric evaluation frequency.
            initial: Optional value available before first evaluation.

        Returns:
            A value reference accepted by controls, selectors, levels, and
            dynamic view properties.
        """
        ref = self.create_value(name, initial=initial) if initial is not _MISSING else ValueRef(str(name))
        self._derives.append(
            DerivedField(
                name=ref.key,
                fn=fn,
                target="value",
                field_id="",
                series=(),
                series_dim="",
                mode="replace",
                over=over,
                window=window,
                max_refresh_hz=max_refresh_hz,
            )
        )
        return ref

    # -- AppSpec assembly -----------------------------------------------------

    def _compose_app_spec_for_backend(self, backend: NeuronBackend):
        return self._compose_startup_data_app_spec_for_backend(
            backend,
            expected_backend_type=NeuronBackend,
        )

__all__ = [
    "DerivedField",
    "LineRecorder",
    "MorphologyRef",
    "SelectionRef",
    "NeuronInlineSource",
    "ValueRef",
]

