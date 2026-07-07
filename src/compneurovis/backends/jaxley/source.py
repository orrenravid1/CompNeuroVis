"""Inline-mode source API for Jaxley backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from compneurovis.backends.base import BackendBase
from compneurovis.backends.jaxley.app_spec import JaxleyAppSpecBuilder
from compneurovis.backends.jaxley.backend import JaxleyBackend
from compneurovis.core.app_spec import AppSpec, LayoutCatalog, LayoutSpec, PANEL_KIND_LINE_PLOT, PANEL_KIND_VIEW_3D, ViewCatalog
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
class JaxleyControlBinding(ControlBinding):
    refresh_externals: bool = False
    refresh_params: bool = False

    def apply(self, backend: JaxleyBackend, value: Any) -> bool:
        self.set(float(value))
        if self.refresh_externals:
            backend.refresh_runtime_externals()
            backend._step_index = 0
        if self.refresh_params:
            backend.refresh_runtime_parameters(preserve_state=True)
        return True


@dataclass
class MorphologyBinding:
    color_field_id: str
    color_map: str = "scalar"
    color_limits: tuple[float, float] | None = (-80.0, 50.0)
    color_norm: str = "auto"
    selectable: bool = True
    _view_id: str = field(init=False, default="")
    _panel_id: str = field(init=False, default="")

    def _register(self, index: int) -> None:
        self._view_id = f"morphology_{index}"
        self._panel_id = f"morphology-panel-{index}"

    def _view_spec(self, geometry_id: str) -> MorphologyViewSpec:
        return MorphologyViewSpec(
            id=self._view_id,
            title="Morphology",
            geometry_id=geometry_id,
            color_field_id=self.color_field_id,
            entity_dim="segment",
            sample_dim=None,
            selectable=self.selectable,
            color_map=self.color_map,
            color_limits=self.color_limits,
            color_norm=self.color_norm,
        )

    def _panel_spec(self):
        from compneurovis.core.app_spec import PanelSpec
        return PanelSpec(id=self._panel_id, kind=PANEL_KIND_VIEW_3D, view_ids=(self._view_id,))


@dataclass
class SegmentHistoryBinding:
    field_id: str = field(default_factory=lambda: JaxleyAppSpecBuilder.HISTORY_FIELD_ID)
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
        from compneurovis.core.app_spec import PanelSpec
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


class _SourceBackend(JaxleyBackend):
    def __init__(
        self,
        *,
        cells: list,
        setup_fn: Callable | None,
        controls: list[ControlBinding],
        actions: list[ActionBinding],
        traces: list[TraceBinding],
        dt: float,
        v_init: float,
        title: str,
        **kwargs,
    ) -> None:
        super().__init__(dt=dt, v_init=v_init, title=title, display_dt=kwargs.pop("display_dt", 50.0), **kwargs)
        self._provided_cells = cells
        self._setup_fn = setup_fn
        self._provided_controls = controls
        self._provided_actions = actions
        self._provided_traces = traces

    def build_cells(self) -> Iterable:
        return self._provided_cells

    def setup_model(self, network, cells):
        if self._setup_fn is not None:
            self._setup_fn(network, cells)

    def control_specs(self) -> dict[str, ControlSpec]:
        return {control._control_id: control._control_spec() for control in self._provided_controls}

    def control_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for control in self._provided_controls:
            get = getattr(control, "get", None)
            if get is not None:
                values[control._control_id] = get()
            else:
                spec = control._control_spec()
                values[control._control_id] = self._ui_state.get(spec.resolved_state_key(), spec.default_value())
        return values

    def action_specs(self) -> dict[str, ActionSpec]:
        return {action._action_id: action._action_spec() for action in self._provided_actions}

    def apply_control(self, control_id: str, value: Any) -> bool:
        for control in self._provided_controls:
            if control._control_id == control_id:
                if not control.apply(self, value):
                    return False
                self._ui_state[control_id] = value
                return True
        return False

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

    def idle_sleep(self) -> float:
        return 1.0 / 60.0

    def _emit_batch(self, times_array, steps: list[Any]) -> None:
        super()._emit_batch(times_array, steps)
        for trace in self._provided_traces:
            trace._begin_frame()
            trace._sample()
        emit_trace_updates(self, self._provided_traces, auto_sample=False)


class JaxleySource(InlineSourceBase):
    DISPLAY_FIELD_ID = JaxleyAppSpecBuilder.DISPLAY_FIELD_ID
    HISTORY_FIELD_ID = JaxleyAppSpecBuilder.HISTORY_FIELD_ID

    def __init__(
        self,
        *,
        cells: list,
        setup: Callable | None,
        dt: float,
        v_init: float,
        backend_kwargs: dict,
        title: str = "CompNeuroVis",
    ) -> None:
        super().__init__(title=title)
        self._cells = cells
        self._setup_fn = setup
        self._dt = dt
        self._v_init = v_init
        self._backend_kwargs = backend_kwargs
        self._morphology_bindings: list[MorphologyBinding] = []
        self._history_bindings: list[SegmentHistoryBinding] = []

    def morphology(
        self,
        *,
        color_field_id: str | None = None,
        color_map: str = "scalar",
        color_limits: tuple[float, float] | None = (-80.0, 50.0),
        color_norm: str = "auto",
        selectable: bool = True,
    ) -> MorphologyHandle:
        binding = MorphologyBinding(
            color_field_id=color_field_id or self.DISPLAY_FIELD_ID,
            color_map=color_map,
            color_limits=color_limits,
            color_norm=color_norm,
            selectable=selectable,
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
        refresh_externals: bool = False,
        refresh_params: bool = False,
    ) -> ControlHandle:
        binding = JaxleyControlBinding(
            name=name,
            label=label,
            get=get,
            set=set,
            min=min,
            max=max,
            refresh_externals=refresh_externals,
            refresh_params=refresh_params,
        )
        self._add_control(binding)
        return ControlHandle(binding)

    def _make_backend(self) -> _SourceBackend:
        return _SourceBackend(
            cells=self._cells,
            setup_fn=self._setup_fn,
            controls=self._controls,
            actions=self._actions,
            traces=self._traces,
            dt=self._dt,
            v_init=self._v_init,
            title=self.title,
            **self._backend_kwargs,
        )

    def _build_app_spec_for_backend(self, backend: BackendBase) -> AppSpec:
        if not isinstance(backend, _SourceBackend):
            raise TypeError(f"JaxleySource expected _SourceBackend, got {type(backend)!r}")
        app_spec = backend.build_startup_data()
        app_spec = _append_morphology_and_history_views(
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


def source(
    *,
    cells: Sequence,
    setup: Callable | None = None,
    dt: float = 0.025,
    v_init: float = -70.0,
    title: str = "CompNeuroVis",
    **kwargs,
) -> JaxleySource:
    """Create a CompNeuroVis Jaxley source for an existing model."""

    return JaxleySource(
        cells=list(cells),
        setup=setup,
        dt=dt,
        v_init=v_init,
        backend_kwargs=kwargs,
        title=title,
    )


__all__ = [
    "JaxleySource",
    "JaxleyControlBinding",
    "MorphologyBinding",
    "MorphologyHandle",
    "SegmentHistoryBinding",
    "SegmentHistoryHandle",
    "source",
]
