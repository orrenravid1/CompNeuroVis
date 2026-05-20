"""Inline-mode attach API for NEURON backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

import numpy as np

from compneurovis.backends.base import BackendBase
from compneurovis.backends.neuron.app_spec import NeuronAppSpecBuilder
from compneurovis.backends.neuron.backend import NeuronBackend
from compneurovis.core.app import AppSpec
from compneurovis.core.app import PANEL_KIND_LINE_PLOT, PANEL_KIND_VIEW_3D
from compneurovis.core.controls import ActionSpec, ControlSpec
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
        del backend
        self.set(float(value))
        return True


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
        from compneurovis.core.app import PanelSpec
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
        from compneurovis.core.app import PanelSpec
        return PanelSpec(id=self._panel_id, kind=PANEL_KIND_VIEW_3D, view_ids=(self._view_id,))


@dataclass
class SegmentHistoryBinding:
    field_id: str = field(default_factory=lambda: NeuronAppSpecBuilder.HISTORY_FIELD_ID)
    title: str = "Trace"
    y_unit: str = "mV"
    rolling_window: float = 500.0
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
            x_unit="ms",
            y_unit=self.y_unit,
            rolling_window=self.rolling_window,
        )

    def _panel_spec(self):
        from compneurovis.core.app import PanelSpec
        return PanelSpec(id=self._panel_id, kind=PANEL_KIND_LINE_PLOT, view_ids=(self._view_id,))


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


class _AttachBackend(NeuronBackend):
    def __init__(
        self,
        *,
        sections: list,
        controls: list[ControlBinding],
        actions: list[ActionBinding],
        traces: list[TraceBinding],
        step_fn: Callable[[], None] | None,
        dt: float,
        v_init: float,
        title: str,
    ) -> None:
        super().__init__(dt=dt, v_init=v_init, title=title, display_dt=0.1)
        self._provided_sections = sections
        self._provided_controls = controls
        self._provided_actions = actions
        self._provided_traces = traces
        self._custom_step_fn = step_fn

    def build_sections(self) -> list:
        return self._provided_sections

    def control_specs(self) -> dict[str, ControlSpec]:
        return {control._control_id: control._control_spec() for control in self._provided_controls}

    def action_specs(self) -> dict[str, ActionSpec]:
        return {action._action_id: action._action_spec() for action in self._provided_actions}

    def apply_control(self, control_id: str, value: Any) -> bool:
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
                return True
        return False

    def _emit_batch(self, times_array: np.ndarray, steps: list[Any]) -> None:
        super()._emit_batch(times_array, steps)
        for trace in self._provided_traces:
            trace._begin_frame()
            trace._sample()
        emit_trace_updates(self, self._provided_traces, auto_sample=False)

    def update(self) -> None:
        if self._custom_step_fn is None:
            super().update()
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
        v_init: float,
        title: str = "CompNeuroVis",
    ) -> None:
        super().__init__(title=title)
        self._sections = sections
        self._step_fn = step
        self._dt = dt
        self._v_init = v_init
        self._morphology_bindings: list[MorphologyBinding] = []
        self._history_bindings: list[SegmentHistoryBinding] = []

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
        title: str = "Trace",
        y_unit: str = "mV",
        rolling_window: float = 500.0,
    ) -> SegmentHistoryHandle:
        binding = SegmentHistoryBinding(
            field_id=field_id or self.HISTORY_FIELD_ID,
            title=title,
            y_unit=y_unit,
            rolling_window=rolling_window,
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

    def _make_backend(self) -> _AttachBackend:
        return _AttachBackend(
            sections=self._sections,
            controls=self._controls,
            actions=self._actions,
            traces=self._traces,
            step_fn=self._step_fn,
            dt=self._dt,
            v_init=self._v_init,
            title=self.title,
        )

    def _build_app_spec_for_backend(self, backend: BackendBase) -> AppSpec:
        if not isinstance(backend, _AttachBackend):
            raise TypeError(f"NeuronAttachSource expected _AttachBackend, got {type(backend)!r}")
        app_spec = backend.build_startup_data()
        _append_morphology_and_history_views(
            app_spec,
            morphology_bindings=self._morphology_bindings,
            history_bindings=self._history_bindings,
            geometry=backend.geometry,
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
) -> None:
    if not morphology_bindings and not history_bindings:
        return
    layout = app_spec.active_layout()
    panels = list(layout.panels)
    panel_grid = list(layout.panel_grid)
    first_row: list[str] = []
    for binding in morphology_bindings:
        view_spec = binding._view_spec(geometry.id)
        app_spec.view_catalog.views[view_spec.id] = view_spec
        panel = binding._panel_spec()
        panels.append(panel)
        first_row.append(panel.id)
    for binding in history_bindings:
        view_spec = binding._view_spec()
        app_spec.view_catalog.views[view_spec.id] = view_spec
        panel = binding._panel_spec()
        panels.append(panel)
        first_row.append(panel.id)
    panel_grid.insert(0, tuple(first_row))
    layout.replace_panels(tuple(panels), tuple(panel_grid))


def attach(
    *,
    sections: Sequence,
    step: Callable[[], None] | None = None,
    dt: float | None = None,
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
    "attach",
]
