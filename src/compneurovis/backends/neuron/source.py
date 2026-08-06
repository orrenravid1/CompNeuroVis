"""Inline-mode source API for NEURON backends.

``source(sections=[...])`` wraps an existing NEURON model without subclassing
``NeuronBackend``. Shared widgets are inherited from
:class:`NeuronInlineSource`; this module adds only the source-specific runtime
and optimized NEURON data producers.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from compneurovis.backends import HistoryCaptureMode
from compneurovis.backends.interaction import _selection_ids_from_internal
from compneurovis.backends.neuron.backend import DisplayConfig, HISTORY_FIELD_ID, NeuronBackend
from compneurovis.backends.neuron.inline import (
    ClickHandler,
    DerivedField,
    KeyHandler,
    LineRecorder,
    NeuronInlineSource,
    _coerce_series_initial,
    _time_coord,
)
from compneurovis.core.field import FieldSpec
from compneurovis.core.messages import EntityClicked, FieldAppend, FieldReplace, Message, MessagePayload, Reset, ValueChange
from compneurovis.inline._ids import slug
from compneurovis.inline.backend import SourceBackendMixin
from compneurovis.inline.data_producers import SeriesProducer
from compneurovis.inline.refs import (
    DataRef,
    MorphologyRef,
    binding_key,
)
from compneurovis.inline.interactions import ActionInteraction, ControlInteraction


def _state_value(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        if value.ndim == 0:
            return value.item()
        return value.tolist()
    return value


@dataclass
class SegmentVariableDisplayBinding:
    name: str
    variables: dict[str, str]
    default: str
    value_key: str
    units: dict[str, str] = field(default_factory=dict)
    color_limits: dict[str, tuple[float, float]] = field(default_factory=dict)
    color_maps: dict[str, str] = field(default_factory=dict)
    _field_id: str = field(init=False, default="")
    _selected: str = field(init=False, default="")
    _ptrs_by_attr: dict[str, tuple[Any, Any] | None] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        if not self.variables:
            raise ValueError("segment variable display needs at least one variable")
        if self.default not in self.variables:
            raise ValueError(f"default variable {self.default!r} is not in variables")
        self._selected = self.default

    def _register(self, index: int) -> None:
        suffix = f"{index}_{slug(self.name)}"
        self._field_id = f"segment_variable_display_{suffix}"

    def apply(self, value: Any) -> bool:
        selected = str(value)
        if selected not in self.variables:
            return False
        self._selected = selected
        return True

    def _initial_field(self, backend: NeuronBackend) -> FieldSpec:
        return FieldSpec(
            id=self._field_id,
            initial_values=self._read_values(backend),
            dims=("segment",),
            coords={"segment": np.asarray(backend.geometry.entity_ids)},
            unit=self.units.get(self._selected) or None,
            attrs=self._field_attrs(),
        )

    def _replace_payload(self, backend: NeuronBackend) -> FieldReplace:
        return FieldReplace(
            field_id=self._field_id,
            values=self._read_values(backend),
            attrs_update=self._field_attrs(),
        )

    def _field_attrs(self) -> dict[str, Any]:
        attrs: dict[str, Any] = {
            "variable": self._selected,
            "unit": self.units.get(self._selected, ""),
        }
        limits = self.color_limits.get(self._selected)
        attrs["color_limits"] = None if limits is None else tuple(float(value) for value in limits)
        attrs["color_map"] = self.color_maps.get(self._selected)
        return attrs

    def _read_values(self, backend: NeuronBackend) -> np.ndarray:
        attr = self.variables[self._selected]
        if attr == "v":
            return np.asarray(backend._read_display_values(), dtype=np.float32)
        ptrs = self._ptrs_by_attr.get(attr)
        if ptrs is None and attr not in self._ptrs_by_attr:
            ptrs = self._build_ptr_vector(backend, attr)
            self._ptrs_by_attr[attr] = ptrs
        if ptrs is None:
            return self._read_values_slow(backend, attr)
        ptr_vector, values_vector = ptrs
        ptr_vector.gather(values_vector)
        return np.asarray(values_vector.as_numpy(), dtype=np.float32).copy()

    def _build_ptr_vector(self, backend: NeuronBackend, attr: str) -> tuple[Any, Any] | None:
        from neuron import h

        section_lookup = {sec.name(): sec for sec in backend.sections}
        ptr_vector = h.PtrVector(len(backend.geometry.entity_ids))
        values_vector = h.Vector(len(backend.geometry.entity_ids))
        for index, (section_name, xloc) in enumerate(zip(backend.geometry.section_names, backend.geometry.xlocs)):
            seg = section_lookup[str(section_name)](float(xloc))
            ref = getattr(seg, f"_ref_{attr}", None)
            if ref is None:
                return None
            ptr_vector.pset(index, ref)
        return ptr_vector, values_vector

    def _read_values_slow(self, backend: NeuronBackend, attr: str) -> np.ndarray:
        section_lookup = {sec.name(): sec for sec in backend.sections}
        values = np.empty(len(backend.geometry.entity_ids), dtype=np.float32)
        for index, (section_name, xloc) in enumerate(zip(backend.geometry.section_names, backend.geometry.xlocs)):
            seg = section_lookup[str(section_name)](float(xloc))
            values[index] = float(getattr(seg, attr, np.nan))
        return values


class SegmentVariableDisplayRef:
    __slots__ = ("_binding",)

    def __init__(self, binding: SegmentVariableDisplayBinding) -> None:
        self._binding = binding

    @property
    def field_id(self) -> str:
        return self._binding._field_id



@dataclass
class SegmentVariableHistoryBinding:
    name: str
    variables: dict[str, str]
    selection_id: str
    unit: str = ""
    max_samples: int = 5000
    _field_id: str = field(init=False, default="")

    def __post_init__(self) -> None:
        if not self.variables:
            raise ValueError("segment variable history needs at least one variable")

    def _register(self, index: int) -> None:
        suffix = f"{index}_{slug(self.name)}"
        self._field_id = f"segment_variable_history_{suffix}"

    def _selected_segment_id(self, backend: NeuronBackend) -> str:
        selected = _selection_ids_from_internal(
            backend.values.get(self.selection_id)
        )
        if selected and selected[-1] in backend._entity_index_by_id:
            return selected[-1]
        return str(backend.geometry.entity_ids[0])

    def _sample_selected(self, backend: NeuronBackend) -> np.ndarray:
        entity_id = self._selected_segment_id(backend)
        index = backend._entity_index_by_id[entity_id]
        section_name = str(backend.geometry.section_names[index])
        xloc = float(backend.geometry.xlocs[index])
        section_lookup = {sec.name(): sec for sec in backend.sections}
        seg = section_lookup[section_name](xloc)
        return np.asarray([float(getattr(seg, attr, np.nan)) for attr in self.variables.values()], dtype=np.float32)

    def _initial_field(self, backend: NeuronBackend) -> FieldSpec:
        from neuron import h

        entity_id = self._selected_segment_id(backend)
        values = self._sample_selected(backend).reshape(len(self.variables), 1, 1)
        return FieldSpec(
            id=self._field_id,
            initial_values=values,
            dims=("variable", "segment", "time"),
            coords={
                "variable": np.asarray(tuple(self.variables.keys())),
                "segment": np.asarray([entity_id]),
                "time": np.asarray([float(h.t)], dtype=np.float32),
            },
            unit=self.unit,
        )

    def _replace_payload(self, backend: NeuronBackend) -> FieldReplace:
        field = self._initial_field(backend)
        return FieldReplace(
            field_id=self._field_id,
            values=field.initial_values,
            coords=dict(field.coords),
        )

    def _append_payload(self, backend: NeuronBackend, times_array: np.ndarray, samples: Sequence[np.ndarray]) -> FieldAppend:
        del backend
        values = np.stack(samples, axis=1).reshape(len(self.variables), 1, len(samples))
        return FieldAppend(
            field_id=self._field_id,
            append_dim="time",
            values=values.astype(np.float32),
            coord_values=times_array,
            max_length=self.max_samples,
        )

@dataclass
class NeuronRefRecorder:
    """PtrVector-backed recorder for NEURON refs declared through source()."""

    field_id: str
    series_dim: str
    series: tuple[str, ...]
    refs: tuple[Any, ...]
    max_samples: int = 5000
    sample_dt: float | None = None
    _ptr_vector: Any = field(init=False, default=None)
    _values_vector: Any = field(init=False, default=None)
    _last_emit_t: float | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        if len(self.refs) != len(self.series):
            raise ValueError("record_refs(...) refs and series must have the same length")

    def sample_vector(self) -> np.ndarray:
        if self._ptr_vector is None:
            self._build_ptr_vector()
        self._ptr_vector.gather(self._values_vector)
        return np.asarray(self._values_vector.as_numpy(), dtype=np.float32).copy()

    def replace_payload(self) -> FieldReplace:
        """A one-sample FieldReplace at the current time -- clears this plot's
        scrolling history in the frontend (backs ``ctx.clear``)."""
        from neuron import h

        values = self.sample_vector().reshape(len(self.series), 1).astype(np.float32)
        self.mark_emitted(float(h.t))
        return FieldReplace(
            field_id=self.field_id,
            values=values,
            coords={
                self.series_dim: np.asarray(self.series),
                "time": np.asarray([float(h.t)], dtype=np.float32),
            },
        )

    def mark_emitted(self, t: float) -> None:
        self._last_emit_t = float(t)

    def sample_indices(self, times: np.ndarray) -> np.ndarray:
        sample_dt = self.sample_dt
        if sample_dt is None or sample_dt <= 0:
            if len(times):
                self.mark_emitted(float(times[-1]))
            return np.arange(len(times), dtype=np.int32)
        if len(times) == 0:
            return np.asarray([], dtype=np.int32)

        interval = float(sample_dt)
        eps = max(1e-9, interval * 1e-6)
        next_t = float(times[0]) if self._last_emit_t is None else self._last_emit_t + interval
        selected: list[int] = []
        for index, raw_t in enumerate(times):
            t = float(raw_t)
            if t + eps < next_t:
                continue
            selected.append(index)
            while next_t <= t + eps:
                next_t += interval
        if selected:
            self.mark_emitted(float(times[selected[-1]]))
        return np.asarray(selected, dtype=np.int32)

    def _build_ptr_vector(self) -> None:
        from neuron import h

        self._ptr_vector = h.PtrVector(len(self.refs))
        self._values_vector = h.Vector(len(self.refs))
        for index, ref in enumerate(self.refs):
            self._ptr_vector.pset(index, ref)


def _recorder_sample_indices(recorder: Any, times_array: np.ndarray) -> np.ndarray:
    sample_indices = getattr(recorder, "sample_indices", None)
    if callable(sample_indices):
        return sample_indices(times_array)
    return np.arange(len(times_array), dtype=np.int32)


def _resolve_ref_record_max_samples(
    *,
    explicit: int | None,
    rolling_window: Any,
    sample_dt: float | None,
    sim_dt: float,
) -> int:
    if explicit is not None:
        return int(explicit)
    window = None if rolling_window is None else float(rolling_window)
    cadence = sample_dt if sample_dt is not None and sample_dt > 0 else sim_dt
    if window is not None and cadence > 0:
        return max(1, int(math.ceil(window / float(cadence))) + 2)
    return 5000


@dataclass
class _SourceStep:
    display_values: np.ndarray | None
    selected_series_values: np.ndarray | None
    segment_variable_values: tuple[np.ndarray, ...]
    recorder_values: tuple[np.ndarray, ...]


class _SourceBackend(SourceBackendMixin, NeuronBackend):
    def __init__(
        self,
        *,
        sections: list,
        controls: list[ControlInteraction],
        actions: list[ActionInteraction],
        series: list[SeriesProducer],
        segment_variable_displays: list[SegmentVariableDisplayBinding],
        segment_variable_histories: list[SegmentVariableHistoryBinding],
        recorders: list[LineRecorder],
        click_handlers: list[ClickHandler],
        key_handlers: list[KeyHandler],
        capture_predicate: ClickHandler | None,
        initial_state: list[tuple[str, Any]],
        derives: list[DerivedField],
        step_fn: Callable[[], None] | None,
        dt: float,
        display_dt: float | None,
        flush_dt: float | None,
        v_init: float,
        display: DisplayConfig | None,
        title: str,
    ) -> None:
        super().__init__(dt=dt, v_init=v_init, title=title, display_dt=display_dt, display=display)
        self._provided_sections = sections
        self._init_source_bindings(controls=controls, actions=actions, series=series)
        self._segment_variable_displays = segment_variable_displays
        self._segment_variable_histories = segment_variable_histories
        for binding in self._segment_variable_displays:
            self._bind_segment_variable_display(binding)
        self._recorders = recorders
        self._click_handlers = click_handlers
        self._key_handlers = key_handlers
        self._capture_predicate = capture_predicate
        self._initial_state_seeds = initial_state
        self._derives = derives
        self._custom_step_fn = step_fn
        # Coalesce emission every `flush_dt` sim-ms (0 = every tick). The buffering
        # itself lives on the base backend; the source only sets the interval.
        self._flush_dt = float(flush_dt) if flush_dt else 0.0

    def build_sections(self) -> list:
        return self._provided_sections


    def _bind_segment_variable_display(self, binding: SegmentVariableDisplayBinding) -> None:
        key = binding.value_key
        self.values.bind(
            key,
            lambda actor, value, _binding=binding, _key=key: actor._apply_segment_variable_display(_binding, _key, value),
            initial=binding._selected,
        )

    def _apply_segment_variable_display(
        self,
        binding: SegmentVariableDisplayBinding,
        key: str,
        value: Any,
    ) -> None:
        if binding.apply(value):
            self.values.set(key, value)
            self.emit_update(binding._replace_payload(self))

    def initialize(self, app_spec) -> None:
        # Base initialize handles the no-display case (it only seeds a selected
        # entity when there is geometry), so no display-specific branch here.
        super().initialize(app_spec)
        updates: dict[str, Any] = {}
        for key, value in self._initial_state_seeds:
            resolved = value(self._interaction_context()) if callable(value) else value
            self.values.set(key, resolved)
            updates[key] = resolved
        if updates:
            self.emit_update(ValueChange(updates))

    def should_capture_series_on_click(self, entity_id: str, context) -> bool:
        if self._capture_predicate is None:
            return True
        return bool(self._capture_predicate(context, entity_id))

    def _reset_backend_field_history(self, field_ids: set | None) -> None:
        super()._reset_backend_field_history(field_ids)
        for recorder in self._recorders:
            if field_ids is None or recorder.field_id in field_ids:
                self.emit_update(recorder.replace_payload())
        for binding in self._segment_variable_histories:
            if field_ids is None or binding._field_id in field_ids:
                self.emit_update(binding._replace_payload(self))

    def _uses_source_step(self) -> bool:
        return bool(self._segment_variable_histories or self._recorders)

    def _sample_source_step(self, *, include_display_values: bool) -> Any:
        display_values = self._read_display_values() if include_display_values and self._display is not None else None
        selected_series_values = None
        if not include_display_values and self._display is not None and self._series_segment_ids:
            selected_series_values = self._read_selected_series_values()
        if include_display_values and not self._uses_source_step():
            return display_values
        return _SourceStep(
            display_values=display_values,
            selected_series_values=selected_series_values,
            segment_variable_values=tuple(
                binding._sample_selected(self) for binding in self._segment_variable_histories
            ),
            recorder_values=tuple(recorder.sample_vector() for recorder in self._recorders),
        )

    def _advance(self) -> None:
        if self._custom_step_fn is None:
            from neuron import h
            h.fadvance()
        else:
            self._custom_step_fn()

    def _on_step(self, t: float) -> None:
        self._observe_derives(t)

    def _sample_step(self) -> Any:
        include_display = self.history_capture_mode == HistoryCaptureMode.FULL and self._display is not None
        return self._sample_source_step(include_display_values=include_display)

    def _emit_batch(self, times_array: np.ndarray, steps: list[Any]) -> None:
        if steps and isinstance(steps[0], _SourceStep):
            if steps[0].display_values is None:
                selected_series_values = None
                if self._display is not None and self._series_segment_ids:
                    selected_series_values = np.stack(
                        [step.selected_series_values for step in steps],
                        axis=1,
                    ).astype(np.float32)
                if self._display is not None:
                    self._emit_on_demand_display_and_series(
                        times_array,
                        self._read_display_values(),
                        selected_series_values,
                    )
                else:
                    self._last_time_value = float(times_array[-1])
            else:
                display_steps = [step.display_values for step in steps]
                super()._emit_batch(times_array, display_steps)
        else:
            super()._emit_batch(times_array, steps)
        for binding in self._segment_variable_displays:
            self.emit_update(binding._replace_payload(self))
        if steps and isinstance(steps[0], _SourceStep):
            for index, binding in enumerate(self._segment_variable_histories):
                samples = [step.segment_variable_values[index] for step in steps]
                self.emit_update(binding._append_payload(self, times_array, samples))
            for index, recorder in enumerate(self._recorders):
                sample_indices = _recorder_sample_indices(recorder, times_array)
                if len(sample_indices) == 0:
                    continue
                values = np.stack(
                    [steps[int(step_index)].recorder_values[index] for step_index in sample_indices],
                    axis=1,
                ).astype(np.float32)
                self.emit_update(
                    FieldAppend(
                        field_id=recorder.field_id,
                        append_dim="time",
                        values=values,
                        coord_values=times_array[sample_indices],
                        max_length=recorder.max_samples,
                    )
                )
        self._emit_source_series_updates(auto_sample=False)
        self._update_derives(times_array)

    def _observe_derives(self, t: float) -> None:
        for derived in self._derives:
            derived.observe(t)

    def _update_derives(self, times_array: np.ndarray) -> None:
        if not self._derives:
            return
        now = time.monotonic()
        t_last = float(times_array[-1])
        for derived in self._derives:
            if not derived.due(now):
                continue
            result = derived.evaluate(now)
            if result is None:
                continue
            if derived.target == "value":
                value = _state_value(result)
                self.values.set(derived.name, value)
                self.emit_update(ValueChange({derived.name: value}))
                continue
            values = derived.field_values(result)
            if derived.mode == "append":
                self.emit_update(
                    FieldAppend(
                        field_id=derived.field_id,
                        append_dim="time",
                        values=values.reshape(len(derived.series), 1),
                        coord_values=np.asarray([t_last], dtype=np.float32),
                        max_length=derived.max_samples,
                    )
                )
            else:
                self.emit_update(FieldReplace(field_id=derived.field_id, values=values))

    def _recorder_replace(self, recorder: LineRecorder) -> FieldReplace:
        from neuron import h

        t = float(h.t)
        mark_emitted = getattr(recorder, "mark_emitted", None)
        if callable(mark_emitted):
            mark_emitted(t)
        values = recorder.sample_vector().reshape(len(recorder.series), 1)
        return FieldReplace(
            field_id=recorder.field_id,
            values=values,
            coords={
                recorder.series_dim: np.asarray(recorder.series),
                "time": np.asarray([t], dtype=np.float32),
            },
        )

    def _emit_segment_variable_replaces(self) -> None:
        for binding in self._segment_variable_displays:
            self.emit_update(binding._replace_payload(self))
        for binding in self._segment_variable_histories:
            self.emit_update(binding._replace_payload(self))
        for recorder in self._recorders:
            self.emit_update(self._recorder_replace(recorder))

    def on_entity_clicked(self, entity_id: str, context) -> bool:
        handled = False
        for fn in self._click_handlers:
            if fn(context, entity_id):
                handled = True
        return handled

    def _after_entity_selection_changed(self, entity_id: str, context) -> None:
        del entity_id, context
        self._emit_segment_variable_replaces()

    def on_key_press(self, key: str, context) -> bool:
        handled = False
        for fn in self._key_handlers:
            if fn(context, key):
                handled = True
        return handled

    def handle(self, message: Message[MessagePayload]) -> None:
        payload = message.payload
        if isinstance(payload, EntityClicked):
            # Capturing a clicked segment changes the selected-trace width; emit the
            # accumulated (old-width) batch before the width changes, so a coalesced
            # flush never mixes step widths.
            self._flush_pending()
        if isinstance(payload, Reset) and self._display is None:
            from neuron import h

            h.finitialize(self.v_init)
            self._last_time_value = float(h.t)
            for derived in self._derives:
                derived.reset()
            self._pending_times = []
            self._pending_steps = []
            self._pending_recorded = []
            self._last_flush_t = None
            self._emit_segment_variable_replaces()
            return
        is_reset = isinstance(payload, Reset)
        super().handle(message)
        if is_reset:
            for derived in self._derives:
                derived.reset()
            self._pending_times = []
            self._pending_steps = []
            self._pending_recorded = []
            self._last_flush_t = None
            self._emit_segment_variable_replaces()

    def idle_sleep(self) -> float:
        return 1.0 / 60.0


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
        self._segment_variable_displays: list[SegmentVariableDisplayBinding] = []
        self._segment_variable_histories: list[SegmentVariableHistoryBinding] = []

    def morphology(
        self,
        *,
        variable: str | Callable[[Any], Any] | None = None,
        color_by: Mapping[str, str] | None = None,
        color: Any | None = None,
        default_color: str | None = None,
        name: str = "Morphology",
        unit: str | None = None,
        units: Mapping[str, str] | None = None,
        color_limits: tuple[float, float] | Mapping[str, tuple[float, float]] | None = None,
        color_map: str = "scalar",
        color_maps: Mapping[str, str] | None = None,
        color_norm: str = "auto",
        background_color: Any = "white",
        max_refresh_hz: float | None = None,
        selected: Any = None,
        selectable: bool = True,
        select_multiple: bool = False,
        panel: bool = True,
    ) -> MorphologyRef:
        """Add an opt-in morphology panel for this NEURON model.

        Args:
            variable: NEURON range-variable name, or callable mapping a segment
                to a NEURON reference. Use this for one fixed color variable.
            color_by: Mapping of user-facing choices to NEURON range-variable
                names. Use with `color` for runtime variable switching.
            color: Dropdown handle or value reference selecting a `color_by`
                entry.
            default_color: Initial `color_by` entry.
            name: User-facing panel title.
            unit: Unit for the fixed or default variable.
            units: Per-entry units used with `color_by`.
            color_limits: One fixed range, or per-entry ranges with
                `color_by`.
            color_map: Color map for the fixed or default variable.
            color_maps: Per-entry color maps used with `color_by`.
            color_norm: Color normalization mode.
            background_color: Canvas background color.
            max_refresh_hz: Maximum morphology repaint rate.
            selected: Initial segment id, or an iterable when
                `select_multiple=True`.
            selectable: Whether pointer clicks change selection.
            select_multiple: Whether more than one segment can be selected.
            panel: Whether to create the visible 3D panel.

        Returns:
            A morphology handle. Pass `handle.selection` to `line()` for
            optimized selected-segment history; use `handle.selected` with
            context value methods.

        Specify either `variable` or `color_by`, not both.
        """
        if color_by is None:
            if color is not None:
                raise ValueError("morphology(color=...) is only valid with color_by=...")
            if variable is None:
                raise ValueError("morphology(...) requires variable=... or color_by=...")
            return super().morphology(
                variable=variable,
                name=name,
                unit=unit,
                color_limits=color_limits if not isinstance(color_limits, Mapping) else None,
                color_map=color_map,
                color_norm=color_norm,
                background_color=background_color,
                max_refresh_hz=max_refresh_hz,
                selected=selected,
                selectable=selectable,
                select_multiple=select_multiple,
                panel=panel,
            )

        if variable is not None:
            raise ValueError("morphology(...) accepts either variable=... or color_by=..., not both")
        if color is None:
            raise ValueError(
                "morphology(color_by=...) requires color=... from an explicit typed control handle "
                "or src.create_value(...)."
            )
        variables = dict(color_by)
        if not variables:
            raise ValueError("morphology(color_by=...) needs at least one variable")
        default = default_color or next(iter(variables))
        if default not in variables:
            raise ValueError(f"default_color {default!r} is not in color_by")

        resolved_units = dict(units or {})
        if unit is not None and default not in resolved_units:
            resolved_units[default] = unit
        if isinstance(color_limits, Mapping):
            resolved_color_limits = dict(color_limits)
        elif color_limits is None:
            resolved_color_limits = {}
        else:
            resolved_color_limits = {key: tuple(color_limits) for key in variables}
        resolved_color_maps = dict(color_maps or {})

        display = self._segment_variable_display(
            f"{name} color",
            variables=variables,
            default=default,
            value_key=binding_key(color),
            units=resolved_units,
            color_limits=resolved_color_limits,
            color_maps=resolved_color_maps,
        )
        return super().morphology(
            variable=variables[default],
            name=name,
            unit=resolved_units.get(default, unit),
            color_limits=None,
            color_map=resolved_color_maps.get(default, color_map),
            color_norm=color_norm,
            color_field_id=display.field_id,
            background_color=background_color,
            max_refresh_hz=max_refresh_hz,
            selected=selected,
            selectable=selectable,
            select_multiple=select_multiple,
            panel=panel,
        )

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
        if not isinstance(selection, DataRef) or selection._field_id != HISTORY_FIELD_ID:
            raise ValueError("record_selection(...) expects morphology_handle.selection")
        binding = SegmentVariableHistoryBinding(
            name=name,
            variables=dict(variables),
            selection_id=selection._selectors["segment"].key,
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

    def _segment_variable_display(
        self,
        name: str,
        *,
        variables: dict[str, str],
        default: str,
        value_key: str,
        units: dict[str, str] | None = None,
        color_limits: dict[str, tuple[float, float]] | None = None,
        color_maps: dict[str, str] | None = None,
    ) -> SegmentVariableDisplayRef:
        binding = SegmentVariableDisplayBinding(
            name=name,
            variables=dict(variables),
            default=default,
            value_key=value_key,
            units={} if units is None else dict(units),
            color_limits={} if color_limits is None else dict(color_limits),
            color_maps={} if color_maps is None else dict(color_maps),
        )
        binding._register(len(self._segment_variable_displays))
        self._segment_variable_displays.append(binding)
        self._add_widget(field_builders=(binding._initial_field,))
        return SegmentVariableDisplayRef(binding)

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

    def _make_backend(self) -> _SourceBackend:
        return _SourceBackend(
            sections=self._sections,
            controls=self._controls,
            actions=self._actions,
            series=self._series,
            segment_variable_displays=self._segment_variable_displays,
            segment_variable_histories=self._segment_variable_histories,
            recorders=self._recorders,
            click_handlers=self._click_handlers,
            key_handlers=self._key_handlers,
            capture_predicate=self._capture_predicate,
            initial_state=self._initial_values,
            derives=self._derives,
            step_fn=self._step_fn,
            dt=self._dt,
            display_dt=self._display_dt,
            flush_dt=self._flush_dt,
            v_init=self._v_init,
            display=self._display,
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
    return NeuronSource(
        sections=list(sections),
        step=step,
        dt=resolved_dt,
        display_dt=display_dt,
        flush_dt=flush_dt,
        v_init=v_init,
        title=title,
    )


__all__ = [
    "NeuronSource",
    "NeuronRefRecorder",
    "source",
]
