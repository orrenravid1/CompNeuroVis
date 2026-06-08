"""Inline-mode attach API for NEURON backends."""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Sequence

import numpy as np

from compneurovis.backends.base import BackendBase
from compneurovis.backends.neuron.app_spec import NeuronAppSpecBuilder
from compneurovis.backends.neuron.backend import NeuronBackend
from compneurovis.core.app_spec import (
    AppSpec,
    DataCatalog,
    InteractionCatalog,
    LayoutCatalog,
    LayoutSpec,
    PANEL_KIND_CONTROLS,
    PANEL_KIND_LINE_PLOT,
    PANEL_KIND_VIEW_3D,
    ViewCatalog,
)
from compneurovis.core.controls import ActionSpec, ChoiceValueSpec, ControlPresentationSpec, ControlSpec
from compneurovis.core.field import FieldSpec
from compneurovis.core.messages import FieldAppend, FieldReplace, Message, MessagePayload, Reset
from compneurovis.core.state import StateBindingSpec
from compneurovis.core.views import LinePlotViewSpec, MorphologyViewSpec
from compneurovis.inline.bindings import (
    ActionBinding,
    ControlBinding,
    ControlHandle,
    TraceBinding,
    append_bindings_to_app_spec,
    emit_trace_updates,
)
from compneurovis.inline.sources import InlineSourceBase


@dataclass
class NeuronControlBinding(ControlBinding):
    def apply(self, backend: NeuronBackend, value: Any) -> bool:
        if _callable_accepts_backend_arg(self.set):
            self.set(backend, float(value))
        else:
            self.set(float(value))
        return True


def _callable_accepts_backend_arg(fn: Callable[..., Any]) -> bool:
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    params = tuple(signature.parameters.values())
    if any(param.kind == inspect.Parameter.VAR_POSITIONAL for param in params):
        return True
    positional = tuple(
        param for param in params
        if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    )
    return len(positional) >= 2


@dataclass
class MorphologyBinding:
    color_field_id: str
    color_map: str = "scalar"
    color_limits: tuple[float, float] | None = (-80.0, 50.0)
    color_norm: str = "auto"
    _view_id: str = field(init=False, default="")
    _panel_id: str = field(init=False, default="")

    def _register(self, index: int) -> None:
        self._view_id = f"morphology_{index}"
        self._panel_id = f"morphology-panel-{index}"

    def _view_spec(self, geometry_id: str) -> MorphologyViewSpec:
        from compneurovis.core.app_spec import PanelSpec
        return MorphologyViewSpec(
            id=self._view_id,
            title="Morphology",
            geometry_id=geometry_id,
            color_field_id=self.color_field_id,
            entity_dim="segment",
            sample_dim=None,
            color_map=self.color_map,
            color_limits=self.color_limits,
            color_norm=self.color_norm,
        )

    def _panel_spec(self):
        from compneurovis.core.app_spec import PanelSpec
        return PanelSpec(id=self._panel_id, kind=PANEL_KIND_VIEW_3D, view_ids=(self._view_id,))


@dataclass
class SegmentHistoryBinding:
    field_id: str = field(default_factory=lambda: NeuronAppSpecBuilder.HISTORY_FIELD_ID)
    title: Any = "Trace"
    panel_title: str | None = None
    x_label: str = "Time"
    y_label: str = "Value"
    y_unit: str = "mV"
    rolling_window: float = 500.0
    pen: Any = "k"
    _view_id: str = field(init=False, default="")
    _panel_id: str = field(init=False, default="")

    def _register(self, index: int) -> None:
        self._view_id = f"segment_history_{index}"
        self._panel_id = f"segment-history-panel-{index}"

    def _view_spec(self) -> LinePlotViewSpec:
        return LinePlotViewSpec(
            id=self._view_id,
            title=self.title,
            field_id=self.field_id,
            x_dim="time",
            selectors={"segment": StateBindingSpec("selected_entity_id")},
            x_label=self.x_label,
            y_label=self.y_label,
            x_unit="ms",
            y_unit=self.y_unit,
            rolling_window=self.rolling_window,
            pen=self.pen,
        )

    def _panel_spec(self):
        from compneurovis.core.app_spec import PanelSpec
        return PanelSpec(id=self._panel_id, kind=PANEL_KIND_LINE_PLOT, view_ids=(self._view_id,), title=self.panel_title)


class MorphologyHandle:
    __slots__ = ("_binding",)

    def __init__(self, binding: MorphologyBinding) -> None:
        self._binding = binding

    @property
    def color_field_id(self) -> str:
        return self._binding.color_field_id


class SegmentHistoryHandle:
    __slots__ = ("_binding",)

    def __init__(self, binding: SegmentHistoryBinding) -> None:
        self._binding = binding

    @property
    def field_id(self) -> str:
        return self._binding.field_id


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(value).strip()).strip("_").lower() or "item"


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

    def _panel_spec(self):
        from compneurovis.core.app_spec import PanelSpec
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
class _AttachStep:
    display_values: np.ndarray
    segment_variable_values: tuple[np.ndarray, ...]


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
        self._custom_step_fn = step_fn

    def build_sections(self) -> list:
        return self._provided_sections

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

    def on_action(self, action_id: str, payload: dict, context: Any) -> bool:
        del payload, context
        for action in self._provided_actions:
            if action._action_id == action_id:
                action.fn()
                if action.resets_fields:
                    for trace in self._provided_traces:
                        self.emit_update(trace._replace_message().payload)
                    self._emit_segment_variable_replaces()
                return True
        return False

    def _sample_step(self) -> Any:
        display_values = self._read_display_values()
        if not self._segment_variable_histories:
            return display_values
        return _AttachStep(
            display_values=display_values,
            segment_variable_values=tuple(
                binding._sample_selected(self) for binding in self._segment_variable_histories
            ),
        )

    def _emit_batch(self, times_array: np.ndarray, steps: list[Any]) -> None:
        if steps and isinstance(steps[0], _AttachStep):
            display_steps = [step.display_values for step in steps]
        else:
            display_steps = steps
        super()._emit_batch(times_array, display_steps)
        for binding in self._segment_variable_displays:
            self.emit_update(binding._replace_payload(self))
        if steps and isinstance(steps[0], _AttachStep):
            for index, binding in enumerate(self._segment_variable_histories):
                samples = [step.segment_variable_values[index] for step in steps]
                self.emit_update(binding._append_payload(self, times_array, samples))
        for trace in self._provided_traces:
            trace._begin_frame()
            trace._sample()
        emit_trace_updates(self, self._provided_traces, auto_sample=False)

    def _emit_segment_variable_replaces(self) -> None:
        for binding in self._segment_variable_displays:
            self.emit_update(binding._replace_payload(self))
        for binding in self._segment_variable_histories:
            self.emit_update(binding._replace_payload(self))

    def on_entity_clicked(self, entity_id: str, context) -> bool:
        del entity_id, context
        for binding in self._segment_variable_histories:
            self.emit_update(binding._replace_payload(self))
        return False

    def handle(self, message: Message[MessagePayload]) -> None:
        is_reset = isinstance(message.payload, Reset)
        super().handle(message)
        if is_reset:
            self._emit_segment_variable_replaces()

    def tick(self) -> None:
        if self._custom_step_fn is None:
            super().tick()
            return
        from neuron import h

        t_target = float(h.t) + self.sim_ms_per_frame()
        steps = []
        times = []
        while True:
            self._custom_step_fn()
            times.append(float(h.t))
            steps.append(self._sample_step())
            if float(h.t) >= t_target:
                break
        self._emit_batch(np.asarray(times, dtype=np.float32), steps)

    def idle_sleep(self) -> float:
        return 1.0 / 60.0


class NeuronAttachSource(InlineSourceBase):
    DISPLAY_FIELD_ID = NeuronAppSpecBuilder.DISPLAY_FIELD_ID
    HISTORY_FIELD_ID = NeuronAppSpecBuilder.HISTORY_FIELD_ID

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
        self._morphology_bindings: list[MorphologyBinding] = []
        self._history_bindings: list[SegmentHistoryBinding] = []
        self._segment_variable_displays: list[SegmentVariableDisplayBinding] = []
        self._segment_variable_histories: list[SegmentVariableHistoryBinding] = []

    def morphology(
        self,
        *,
        color_field_id: str | None = None,
        color_map: str = "scalar",
        color_limits: tuple[float, float] | None = (-80.0, 50.0),
        color_norm: str = "auto",
    ) -> MorphologyHandle:
        binding = MorphologyBinding(
            color_field_id=color_field_id or self.DISPLAY_FIELD_ID,
            color_map=color_map,
            color_limits=color_limits,
            color_norm=color_norm,
        )
        binding._register(len(self._morphology_bindings))
        self._morphology_bindings.append(binding)
        return MorphologyHandle(binding)

    def history(
        self,
        *,
        field_id: str | None = None,
        title: Any = "Trace",
        panel_title: str | None = None,
        x_label: str = "Time",
        y_label: str = "Value",
        y_unit: str = "mV",
        rolling_window: float = 500.0,
        pen: Any = "k",
    ) -> SegmentHistoryHandle:
        binding = SegmentHistoryBinding(
            field_id=field_id or self.HISTORY_FIELD_ID,
            title=title,
            panel_title=panel_title,
            x_label=x_label,
            y_label=y_label,
            y_unit=y_unit,
            rolling_window=rolling_window,
            pen=pen,
        )
        binding._register(len(self._history_bindings))
        self._history_bindings.append(binding)
        return SegmentHistoryHandle(binding)

    def control(
        self,
        name: str,
        *,
        label: str,
        get: Callable[[], float],
        set: Callable[[Any], None],
        min: float = 0.0,
        max: float = 1.0,
    ) -> ControlHandle:
        binding = NeuronControlBinding(name=name, label=label, get=get, set=set, min=min, max=max)
        self._add_control(binding)
        return ControlHandle(binding)

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
        return SegmentVariableHistoryHandle(binding)

    def _make_backend(self) -> _AttachBackend:
        return _AttachBackend(
            sections=self._sections,
            controls=self._controls,
            actions=self._actions,
            traces=self._traces,
            segment_variable_displays=self._segment_variable_displays,
            segment_variable_histories=self._segment_variable_histories,
            step_fn=self._step_fn,
            dt=self._dt,
            display_dt=self._display_dt,
            v_init=self._v_init,
            title=self.title,
        )

    def _build_app_spec_for_backend(self, backend: BackendBase) -> AppSpec:
        if not isinstance(backend, _AttachBackend):
            raise TypeError(f"NeuronAttachSource expected _AttachBackend, got {type(backend)!r}")
        app_spec = backend.build_startup_data()
        app_spec = _append_morphology_and_history_views(
            app_spec,
            morphology_bindings=self._morphology_bindings,
            history_bindings=self._history_bindings,
            geometry=backend.geometry,
        )
        app_spec = _append_segment_variable_bindings(
            app_spec,
            backend=backend,
            display_bindings=self._segment_variable_displays,
            history_bindings=self._segment_variable_histories,
        )
        return append_bindings_to_app_spec(
            app_spec,
            traces=self._traces,
            controls=self._controls,
            actions=self._actions,
        )


def _append_morphology_and_history_views(
    app_spec: AppSpec,
    *,
    morphology_bindings: list[MorphologyBinding],
    history_bindings: list[SegmentHistoryBinding],
    geometry,
) -> AppSpec:
    if not morphology_bindings and not history_bindings:
        return app_spec
    views = dict(app_spec.view_catalog.views)
    layouts = dict(app_spec.layout_catalog.layouts)
    layout = layouts[app_spec.layout_catalog.active]
    panels = list(layout.panels)
    panel_grid = list(layout.panel_grid)
    first_row: list[str] = []
    for binding in morphology_bindings:
        view_spec = binding._view_spec(geometry.id)
        views[view_spec.id] = view_spec
        panel = binding._panel_spec()
        panels.append(panel)
        first_row.append(panel.id)
    for binding in history_bindings:
        view_spec = binding._view_spec()
        views[view_spec.id] = view_spec
        panel = binding._panel_spec()
        panels.append(panel)
        first_row.append(panel.id)
    panel_grid.insert(0, tuple(first_row))
    layouts[app_spec.layout_catalog.active] = LayoutSpec(
        title=layout.title,
        panels=tuple(panels),
        panel_grid=tuple(panel_grid),
    )
    return AppSpec(
        data=app_spec.data,
        view_catalog=ViewCatalog(
            views=views,
            operators=app_spec.view_catalog.operators,
        ),
        interactions=app_spec.interactions,
        layout_catalog=LayoutCatalog(
            layouts=layouts,
            active=app_spec.layout_catalog.active,
        ),
        metadata=app_spec.metadata,
    )


def _append_segment_variable_bindings(
    app_spec: AppSpec,
    *,
    backend: _AttachBackend,
    display_bindings: list[SegmentVariableDisplayBinding],
    history_bindings: list[SegmentVariableHistoryBinding],
) -> AppSpec:
    if not display_bindings and not history_bindings:
        return app_spec

    fields = dict(app_spec.data.fields)
    geometries = dict(app_spec.data.geometries)
    views = dict(app_spec.view_catalog.views)
    operators = dict(app_spec.view_catalog.operators)
    controls = dict(app_spec.interactions.controls)
    actions = dict(app_spec.interactions.actions)
    layouts = dict(app_spec.layout_catalog.layouts)
    layout = layouts[app_spec.layout_catalog.active]
    panels = list(layout.panels)
    panel_grid = list(layout.panel_grid)

    for binding in display_bindings:
        fields[binding._field_id] = binding._initial_field(backend)
        controls[binding._control_id] = binding._control_spec()
    for binding in history_bindings:
        fields[binding._field_id] = binding._initial_field(backend)
        views[binding._view_id] = binding._view_spec()
        panel = binding._panel_spec()
        panels.append(panel)
        if panel_grid:
            panel_grid[0] = (*panel_grid[0], panel.id)
        else:
            panel_grid.append((panel.id,))

    control_ids = tuple(binding._control_id for binding in display_bindings)
    if control_ids:
        for index, panel in enumerate(panels):
            if panel.kind == PANEL_KIND_CONTROLS:
                panels[index] = replace(
                    panel,
                    control_ids=tuple(dict.fromkeys((*panel.control_ids, *control_ids))),
                )
                break
        else:
            from compneurovis.core.app_spec import PanelSpec

            panel = PanelSpec(id="controls-panel", kind=PANEL_KIND_CONTROLS, control_ids=control_ids)
            panels.append(panel)
            panel_grid.append((panel.id,))

    layouts[app_spec.layout_catalog.active] = LayoutSpec(
        title=layout.title,
        panels=tuple(panels),
        panel_grid=tuple(panel_grid),
    )
    return AppSpec(
        data=DataCatalog(fields=fields, geometries=geometries),
        view_catalog=ViewCatalog(views=views, operators=operators),
        interactions=InteractionCatalog(controls=controls, actions=actions),
        layout_catalog=LayoutCatalog(
            layouts=layouts,
            active=app_spec.layout_catalog.active,
        ),
        metadata=app_spec.metadata,
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
    "MorphologyBinding",
    "MorphologyHandle",
    "NeuronAttachSource",
    "NeuronControlBinding",
    "SegmentHistoryBinding",
    "SegmentHistoryHandle",
    "SegmentVariableDisplayBinding",
    "SegmentVariableDisplayHandle",
    "SegmentVariableHistoryBinding",
    "SegmentVariableHistoryHandle",
    "attach",
]
