"""Inline-mode attach API for NEURON backends.

``attach(sections=[...])`` wraps an existing NEURON model without subclassing
``NeuronBackend``. View/panel composition (``morphology``, ``history``, ``line``,
``layout``) is inherited from :class:`NeuronInlineSource`; this module adds only
the attach-specific runtime backend and the ``segment_variable_*`` bindings that
need per-tick sampling the wrapped model does not provide on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np

from compneurovis.backends import HistoryCaptureMode
from compneurovis.backends.neuron.backend import NeuronBackend
from compneurovis.backends.neuron.inline import (
    ClickHandler,
    KeyHandler,
    LineRecorder,
    NeuronActionBinding,
    NeuronInlineSource,
    PanelHandle,
    _coerce_series_initial,
    _call_with_args,
    _slug,
    _time_coord,
)
from compneurovis.core.app_spec import PANEL_KIND_LINE_PLOT, PanelSpec
from compneurovis.core.controls import ActionSpec, ChoiceValueSpec, ControlPresentationSpec, ControlSpec
from compneurovis.core.field import FieldSpec
from compneurovis.core.messages import BindingValuePatch, FieldAppend, FieldReplace, Message, MessagePayload, Reset
from compneurovis.core.state import StateBindingSpec
from compneurovis.core.views import LinePlotViewSpec
from compneurovis.inline.bindings import (
    ActionBinding,
    ControlBinding,
    TraceBinding,
    emit_trace_updates,
)


@dataclass
class SegmentVariableDisplayBinding:
    name: str
    variables: dict[str, str]
    default: str
    label: str
    units: dict[str, str] = field(default_factory=dict)
    color_limits: dict[str, tuple[float, float]] = field(default_factory=dict)
    _field_id: str = field(init=False, default="")
    _control_id: str = field(init=False, default="")
    _selected: str = field(init=False, default="")
    _ptrs_by_attr: dict[str, tuple[Any, Any] | None] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        if not self.variables:
            raise ValueError("segment variable display needs at least one variable")
        if self.default not in self.variables:
            raise ValueError(f"default variable {self.default!r} is not in variables")
        self._selected = self.default

    def _register(self, index: int) -> None:
        suffix = f"{index}_{_slug(self.name)}"
        self._field_id = f"segment_variable_display_{suffix}"
        self._control_id = f"segment_variable_control_{suffix}"

    def _control_spec(self) -> ControlSpec:
        return ControlSpec(
            id=self._control_id,
            label=self.label,
            value_spec=ChoiceValueSpec(default=self.default, options=tuple(self.variables.keys())),
            presentation=ControlPresentationSpec(kind="dropdown"),
            send_to_backend=True,
        )

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


class SegmentVariableDisplayHandle:
    __slots__ = ("_binding",)

    def __init__(self, binding: SegmentVariableDisplayBinding) -> None:
        self._binding = binding

    @property
    def field_id(self) -> str:
        return self._binding._field_id

    @property
    def control_id(self) -> str:
        return self._binding._control_id


@dataclass
class SegmentVariableHistoryBinding:
    name: str
    variables: dict[str, str]
    title: Any = field(default_factory=lambda: StateBindingSpec("selected_entity_label"))
    panel_title: str | None = None
    x_label: str = "Time"
    y_label: str = "Value"
    y_unit: str = ""
    rolling_window: float = 500.0
    max_samples: int = 5000
    y_min: float | None = None
    y_max: float | None = None
    series_colors: dict[str, Any] = field(default_factory=dict)
    _field_id: str = field(init=False, default="")
    _view_id: str = field(init=False, default="")
    _panel_id: str = field(init=False, default="")

    def __post_init__(self) -> None:
        if not self.variables:
            raise ValueError("segment variable history needs at least one variable")

    def _register(self, index: int) -> None:
        suffix = f"{index}_{_slug(self.name)}"
        self._field_id = f"segment_variable_history_{suffix}"
        self._view_id = f"segment_variable_history_view_{suffix}"
        self._panel_id = f"segment-variable-history-panel-{suffix}"

    def _selected_segment_id(self, backend: NeuronBackend) -> str:
        selected = backend._ui_state.get("selected_entity_id")
        if selected is not None and str(selected) in backend._entity_index_by_id:
            return str(selected)
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
            unit=self.y_unit,
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

    def _view_spec(self) -> LinePlotViewSpec:
        return LinePlotViewSpec(
            id=self._view_id,
            title=self.title,
            field_id=self._field_id,
            x_dim="time",
            series_dim="variable",
            selectors={"segment": StateBindingSpec("selected_entity_id")},
            x_label=self.x_label,
            y_label=self.y_label,
            x_unit="ms",
            y_unit=self.y_unit,
            rolling_window=self.rolling_window,
            trim_to_rolling_window=True,
            y_min=self.y_min,
            y_max=self.y_max,
            series_colors=dict(self.series_colors),
        )

    def _panel_spec(self) -> PanelSpec:
        return PanelSpec(
            id=self._panel_id,
            kind=PANEL_KIND_LINE_PLOT,
            view_ids=(self._view_id,),
            title=self.panel_title,
        )


class SegmentVariableHistoryHandle:
    __slots__ = ("_binding",)

    def __init__(self, binding: SegmentVariableHistoryBinding) -> None:
        self._binding = binding

    @property
    def field_id(self) -> str:
        return self._binding._field_id

    @property
    def view_id(self) -> str:
        return self._binding._view_id


@dataclass
class NeuronRefLineRecorder:
    """PtrVector-backed recorder for NEURON refs declared through attach()."""

    field_id: str
    series_dim: str
    series: tuple[str, ...]
    refs: tuple[Any, ...]
    max_samples: int = 5000
    _ptr_vector: Any = field(init=False, default=None)
    _values_vector: Any = field(init=False, default=None)

    def __post_init__(self) -> None:
        if len(self.refs) != len(self.series):
            raise ValueError("line_refs(...) refs and series must have the same length")

    def sample_vector(self) -> np.ndarray:
        if self._ptr_vector is None:
            self._build_ptr_vector()
        self._ptr_vector.gather(self._values_vector)
        return np.asarray(self._values_vector.as_numpy(), dtype=np.float32).copy()

    def _build_ptr_vector(self) -> None:
        from neuron import h

        self._ptr_vector = h.PtrVector(len(self.refs))
        self._values_vector = h.Vector(len(self.refs))
        for index, ref in enumerate(self.refs):
            self._ptr_vector.pset(index, ref)


class NeuronRefLineHandle(PanelHandle):
    __slots__ = ("_recorder", "_view_id")

    def __init__(self, recorder: NeuronRefLineRecorder, *, panel_id: str, view_id: str) -> None:
        super().__init__(panel_id)
        object.__setattr__(self, "_recorder", recorder)
        object.__setattr__(self, "_view_id", view_id)

    @property
    def field_id(self) -> str:
        return self._recorder.field_id

    @property
    def view_id(self) -> str:
        return self._view_id

    @property
    def panel_id(self) -> str:
        return self.id


@dataclass
class _AttachStep:
    display_values: np.ndarray | None
    selected_trace_values: np.ndarray | None
    segment_variable_values: tuple[np.ndarray, ...]
    recorder_values: tuple[np.ndarray, ...]


class _AttachBackend(NeuronBackend):
    def __init__(
        self,
        *,
        sections: list,
        controls: list[ControlBinding],
        actions: list[ActionBinding],
        traces: list[TraceBinding],
        segment_variable_displays: list[SegmentVariableDisplayBinding],
        segment_variable_histories: list[SegmentVariableHistoryBinding],
        recorders: list[LineRecorder],
        click_handlers: list[ClickHandler],
        key_handlers: list[KeyHandler],
        capture_predicate: ClickHandler | None,
        initial_state: list[tuple[str, Any]],
        step_fn: Callable[[], None] | None,
        dt: float,
        display_dt: float | None,
        v_init: float,
        title: str,
    ) -> None:
        super().__init__(dt=dt, v_init=v_init, title=title, display_dt=display_dt)
        self._provided_sections = sections
        self._provided_controls = controls
        self._provided_actions = actions
        self._provided_traces = traces
        self._segment_variable_displays = segment_variable_displays
        self._segment_variable_histories = segment_variable_histories
        self._recorders = recorders
        self._click_handlers = click_handlers
        self._key_handlers = key_handlers
        self._capture_predicate = capture_predicate
        self._initial_state_seeds = initial_state
        self._custom_step_fn = step_fn

    def build_sections(self) -> list:
        return self._provided_sections

    def initialize(self, app_spec) -> None:
        super().initialize(app_spec)
        for key, value in self._initial_state_seeds:
            resolved = _call_with_args(value, self) if callable(value) else value
            self._ui_state[key] = resolved
            self.emit_update(BindingValuePatch({key: resolved}))

    def control_specs(self) -> dict[str, ControlSpec]:
        controls = {control._control_id: control._control_spec() for control in self._provided_controls}
        controls.update({binding._control_id: binding._control_spec() for binding in self._segment_variable_displays})
        return controls

    def action_specs(self) -> dict[str, ActionSpec]:
        return {action._action_id: action._action_spec() for action in self._provided_actions}

    def apply_control(self, control_id: str, value: Any) -> bool:
        for binding in self._segment_variable_displays:
            if binding._control_id == control_id:
                if not binding.apply(value):
                    return False
                self.emit_update(binding._replace_payload(self))
                return True
        for control in self._provided_controls:
            if control._control_id == control_id:
                return control.apply(self, value)
        return super().apply_control(control_id, value)

    def should_capture_trace_on_click(self, entity_id: str, context) -> bool:
        if self._capture_predicate is None:
            return True
        return bool(_call_with_args(self._capture_predicate, entity_id, context))

    def on_action(self, action_id: str, payload: dict, context: Any) -> bool:
        for action in self._provided_actions:
            if action._action_id == action_id:
                if isinstance(action, NeuronActionBinding):
                    action.invoke(context, payload if isinstance(payload, dict) else {})
                else:
                    action.fn()
                if action.resets_fields:
                    for trace in self._provided_traces:
                        self.emit_update(trace._replace_message().payload)
                    self._emit_segment_variable_replaces()
                return True
        return False

    def _uses_attach_step(self) -> bool:
        return bool(self._segment_variable_histories or self._recorders)

    def _sample_attach_step(self, *, include_display_values: bool) -> Any:
        display_values = self._read_display_values() if include_display_values else None
        selected_trace_values = None
        if not include_display_values and self._trace_segment_ids:
            selected_trace_values = self._read_selected_trace_values()
        if include_display_values and not self._uses_attach_step():
            return display_values
        return _AttachStep(
            display_values=display_values,
            selected_trace_values=selected_trace_values,
            segment_variable_values=tuple(
                binding._sample_selected(self) for binding in self._segment_variable_histories
            ),
            recorder_values=tuple(recorder.sample_vector() for recorder in self._recorders),
        )

    def _sample_step(self) -> Any:
        return self._sample_attach_step(include_display_values=True)

    def _emit_batch(self, times_array: np.ndarray, steps: list[Any]) -> None:
        if steps and isinstance(steps[0], _AttachStep):
            if steps[0].display_values is None:
                selected_trace_values = None
                if self._trace_segment_ids:
                    selected_trace_values = np.stack(
                        [step.selected_trace_values for step in steps],
                        axis=1,
                    ).astype(np.float32)
                self._emit_on_demand_display_and_trace(
                    times_array,
                    self._read_display_values(),
                    selected_trace_values,
                )
            else:
                display_steps = [step.display_values for step in steps]
                super()._emit_batch(times_array, display_steps)
        else:
            super()._emit_batch(times_array, steps)
        for binding in self._segment_variable_displays:
            self.emit_update(binding._replace_payload(self))
        if steps and isinstance(steps[0], _AttachStep):
            for index, binding in enumerate(self._segment_variable_histories):
                samples = [step.segment_variable_values[index] for step in steps]
                self.emit_update(binding._append_payload(self, times_array, samples))
            for index, recorder in enumerate(self._recorders):
                values = np.stack([step.recorder_values[index] for step in steps], axis=1).astype(np.float32)
                self.emit_update(
                    FieldAppend(
                        field_id=recorder.field_id,
                        append_dim="time",
                        values=values,
                        coord_values=times_array,
                        max_length=recorder.max_samples,
                    )
                )
        for trace in self._provided_traces:
            trace._begin_frame()
            trace._sample()
        emit_trace_updates(self, self._provided_traces, auto_sample=False)

    def _recorder_replace(self, recorder: LineRecorder) -> FieldReplace:
        from neuron import h

        values = recorder.sample_vector().reshape(len(recorder.series), 1)
        return FieldReplace(
            field_id=recorder.field_id,
            values=values,
            coords={
                recorder.series_dim: np.asarray(recorder.series),
                "time": np.asarray([float(h.t)], dtype=np.float32),
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
        for binding in self._segment_variable_histories:
            self.emit_update(binding._replace_payload(self))
        handled = False
        for fn in self._click_handlers:
            if _call_with_args(fn, entity_id, context):
                handled = True
        return handled

    def on_key_press(self, key: str, context) -> bool:
        handled = False
        for fn in self._key_handlers:
            if _call_with_args(fn, key, context):
                handled = True
        return handled

    def handle(self, message: Message[MessagePayload]) -> None:
        is_reset = isinstance(message.payload, Reset)
        super().handle(message)
        if is_reset:
            self._emit_segment_variable_replaces()

    def tick(self) -> None:
        from neuron import h

        include_display_values = self.history_capture_mode == HistoryCaptureMode.FULL
        t_target = float(h.t) + self.sim_ms_per_frame()
        steps = []
        recorded_frames: list[np.ndarray] = []
        times = []
        while True:
            if self._custom_step_fn is None:
                h.fadvance()
            else:
                self._custom_step_fn()
            times.append(float(h.t))
            steps.append(self._sample_attach_step(include_display_values=include_display_values))
            recorded = self._read_recorded_values()
            if recorded is not None:
                recorded_frames.append(recorded)
            if float(h.t) >= t_target:
                break
        times_array = np.asarray(times, dtype=np.float32)
        self._emit_batch(times_array, steps)

        if recorded_frames:
            recorded_batch = np.stack(recorded_frames, axis=1)
            self.on_recorded_samples(
                times_array,
                {name: recorded_batch[index] for index, name in enumerate(self._recorded_names)},
            )

    def idle_sleep(self) -> float:
        return 1.0 / 60.0


class NeuronAttachSource(NeuronInlineSource):
    """Inline source that wraps an existing NEURON model (raw sections)."""

    def __init__(
        self,
        *,
        sections: list,
        step: Callable[[], None] | None,
        dt: float,
        display_dt: float | None,
        v_init: float,
        title: str = "CompNeuroVis",
    ) -> None:
        super().__init__(title=title)
        self._sections = sections
        self._step_fn = step
        self._dt = dt
        self._display_dt = display_dt
        self._v_init = v_init
        self._segment_variable_displays: list[SegmentVariableDisplayBinding] = []
        self._segment_variable_histories: list[SegmentVariableHistoryBinding] = []

    def segment_variable_display(
        self,
        name: str,
        *,
        variables: dict[str, str],
        default: str,
        label: str = "Visualized variable",
        units: dict[str, str] | None = None,
        color_limits: dict[str, tuple[float, float]] | None = None,
    ) -> SegmentVariableDisplayHandle:
        binding = SegmentVariableDisplayBinding(
            name=name,
            variables=dict(variables),
            default=default,
            label=label,
            units={} if units is None else dict(units),
            color_limits={} if color_limits is None else dict(color_limits),
        )
        binding._register(len(self._segment_variable_displays))
        self._segment_variable_displays.append(binding)
        self._add_field(binding._initial_field)
        self._add_extra_control(binding._control_spec())
        return SegmentVariableDisplayHandle(binding)

    def segment_variable_history(
        self,
        name: str,
        *,
        variables: dict[str, str],
        title: Any = None,
        panel_title: str | None = None,
        x_label: str = "Time",
        y_label: str = "Value",
        y_unit: str = "",
        rolling_window: float = 500.0,
        max_samples: int = 5000,
        y_min: float | None = None,
        y_max: float | None = None,
        series_colors: dict[str, Any] | None = None,
    ) -> SegmentVariableHistoryHandle:
        binding = SegmentVariableHistoryBinding(
            name=name,
            variables=dict(variables),
            title=StateBindingSpec("selected_entity_label") if title is None else title,
            panel_title=panel_title,
            x_label=x_label,
            y_label=y_label,
            y_unit=y_unit,
            rolling_window=rolling_window,
            max_samples=max_samples,
            y_min=y_min,
            y_max=y_max,
            series_colors={} if series_colors is None else dict(series_colors),
        )
        binding._register(len(self._segment_variable_histories))
        self._segment_variable_histories.append(binding)
        self._add_field(binding._initial_field)
        self._add_view(binding._view_spec())
        self._add_panel(binding._panel_spec())
        return SegmentVariableHistoryHandle(binding)

    def line_refs(
        self,
        name: str,
        *,
        refs: Sequence[Any],
        series: Sequence[str],
        field_id: str | None = None,
        max_samples: int = 5000,
        unit: str | None = None,
        x: str | None = "time",
        by: str | None = None,
        select: dict[str, Any] | None = None,
        panel_id: str | None = None,
        initial: Sequence[float] | np.ndarray | None = None,
        **style: Any,
    ) -> NeuronRefLineHandle:
        """Declare a line plot sampled from NEURON refs via PtrVector.

        This is the attach-specific fast path for high-frequency NEURON values.
        Generic ``line(record=...)`` remains available for non-ref callables.
        """

        labels = tuple(str(item) for item in series)
        ref_tuple = tuple(refs)
        if not labels:
            raise ValueError("line_refs(...) requires at least one series label")
        if len(ref_tuple) != len(labels):
            raise ValueError("line_refs(...) refs and series must have the same length")

        slug = _slug(name)
        resolved_field_id = field_id or f"{slug}_field"
        view_id = f"{slug}_plot"
        resolved_panel_id = panel_id or f"{slug}-panel"
        series_dim = by or "series"
        recorder = NeuronRefLineRecorder(
            field_id=resolved_field_id,
            series_dim=series_dim,
            series=labels,
            refs=ref_tuple,
            max_samples=max_samples,
        )

        def build_field(backend: NeuronBackend) -> FieldSpec:
            raw: Any = initial if initial is not None else recorder.sample_vector()
            values = _coerce_series_initial(raw, len(labels))
            return FieldSpec(
                id=resolved_field_id,
                initial_values=values,
                dims=(series_dim, "time"),
                coords={
                    series_dim: np.asarray(labels),
                    "time": _time_coord(backend),
                },
                unit=unit,
            )

        self._recorders.append(recorder)
        self._add_field(build_field)

        view_kwargs = dict(style)
        title = view_kwargs.pop("title", name)
        self._add_view(
            LinePlotViewSpec(
                id=view_id,
                title=title,
                field_id=resolved_field_id,
                x_dim=x,
                series_dim=series_dim,
                selectors={} if select is None else dict(select),
                **view_kwargs,
            )
        )
        self._add_panel(PanelSpec(id=resolved_panel_id, kind=PANEL_KIND_LINE_PLOT, view_ids=(view_id,)))
        return NeuronRefLineHandle(recorder, panel_id=resolved_panel_id, view_id=view_id)

    def _make_backend(self) -> _AttachBackend:
        return _AttachBackend(
            sections=self._sections,
            controls=self._controls,
            actions=self._actions,
            traces=self._traces,
            segment_variable_displays=self._segment_variable_displays,
            segment_variable_histories=self._segment_variable_histories,
            recorders=self._recorders,
            click_handlers=self._click_handlers,
            key_handlers=self._key_handlers,
            capture_predicate=self._capture_predicate,
            initial_state=self._initial_state,
            step_fn=self._step_fn,
            dt=self._dt,
            display_dt=self._display_dt,
            v_init=self._v_init,
            title=self.title,
        )


def attach(
    *,
    sections: Sequence,
    step: Callable[[], None] | None = None,
    dt: float | None = None,
    display_dt: float | None = 0.1,
    v_init: float = -65.0,
    title: str = "CompNeuroVis",
) -> NeuronAttachSource:
    """Attach CompNeuroVis to an existing NEURON model."""

    from neuron import h

    resolved_dt = float(dt) if dt is not None else float(h.dt)
    return NeuronAttachSource(
        sections=list(sections),
        step=step,
        dt=resolved_dt,
        display_dt=display_dt,
        v_init=v_init,
        title=title,
    )


__all__ = [
    "NeuronAttachSource",
    "NeuronRefLineHandle",
    "NeuronRefLineRecorder",
    "PanelHandle",
    "SegmentVariableDisplayBinding",
    "SegmentVariableDisplayHandle",
    "SegmentVariableHistoryBinding",
    "SegmentVariableHistoryHandle",
    "attach",
]
