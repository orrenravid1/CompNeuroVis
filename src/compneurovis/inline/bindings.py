"""Binding and handle objects for inline-mode trace, control, and action registration."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable

import numpy as np

from compneurovis.backends.base import BackendBase
from compneurovis.core.app import (
    AppSpec,
    DataCatalog,
    InteractionCatalog,
    LayoutCatalog,
    LayoutSpec,
    PANEL_KIND_CONTROLS,
    ViewCatalog,
)
from compneurovis.core.controls import ActionSpec, ControlSpec, ScalarValueSpec
from compneurovis.core.field import FieldSpec
from compneurovis.core.messages import FieldAppend, FieldReplace, update_message
from compneurovis.core.views import LinePlotViewSpec

SeriesReaders = Callable[[], float] | dict[str, Callable[[], float]]


@dataclass
class TraceBinding:
    name: str
    read: SeriesReaders
    x: Callable[[], float]
    rolling_window: float = 500.0
    y_min: float | None = None
    y_max: float | None = None
    y_unit: str = "a.u."
    x_unit: str = "ms"
    max_samples: int = 2400
    _field_id: str = field(init=False, default="")
    _view_id: str = field(init=False, default="")
    _buf_x: list = field(init=False, default_factory=list)
    _buf_vals: list = field(init=False, default_factory=list)
    _sampled_this_frame: bool = field(init=False, default=False)

    def _register(self, index: int) -> None:
        self._field_id = f"field_{index}_{self.name}"
        self._view_id = f"view_{index}_{self.name}"

    def _series(self) -> dict[str, Callable[[], float]]:
        if callable(self.read):
            return {self.name: self.read}
        return self.read

    def _begin_frame(self) -> None:
        self._sampled_this_frame = False

    def _sample(self) -> None:
        series = self._series()
        self._buf_x.append(self.x())
        self._buf_vals.append([fn() for fn in series.values()])
        self._sampled_this_frame = True

    def _drain_message(self):
        if not self._buf_x:
            return None
        xs = self._buf_x[:]
        vals = self._buf_vals[:]
        self._buf_x.clear()
        self._buf_vals.clear()
        n_series = len(self._series())
        values = np.array(vals, dtype=np.float32).reshape(len(xs), n_series).T
        return update_message(
            FieldAppend(
                field_id=self._field_id,
                append_dim="time",
                values=values,
                coord_values=np.array(xs, dtype=np.float32),
                max_length=self.max_samples,
            )
        )

    def _field_spec(self) -> FieldSpec:
        series = self._series()
        return FieldSpec(
            id=self._field_id,
            initial_values=np.array([[fn()] for fn in series.values()], dtype=np.float32),
            dims=("series", "time"),
            coords={
                "series": np.array(list(series.keys())),
                "time": np.array([self.x()], dtype=np.float32),
            },
            unit=self.y_unit,
        )

    def _view_spec(self) -> LinePlotViewSpec:
        series = self._series()
        return LinePlotViewSpec(
            id=self._view_id,
            title=self.name,
            field_id=self._field_id,
            x_dim="time",
            series_dim="series",
            x_unit=self.x_unit,
            y_unit=self.y_unit,
            rolling_window=self.rolling_window,
            trim_to_rolling_window=True,
            y_min=self.y_min,
            y_max=self.y_max,
            show_legend=len(series) > 1,
        )

    def _panel_spec(self):
        from compneurovis.core.app import PANEL_KIND_LINE_PLOT, PanelSpec

        return PanelSpec(
            id=f"panel_{self._view_id}",
            kind=PANEL_KIND_LINE_PLOT,
            view_ids=(self._view_id,),
        )

    def _replace_message(self):
        series = self._series()
        values = np.array([[fn()] for fn in series.values()], dtype=np.float32)
        return update_message(
            FieldReplace(
                field_id=self._field_id,
                values=values,
                coords={
                    "series": np.array(list(series.keys())),
                    "time": np.array([self.x()], dtype=np.float32),
                },
            )
        )


@dataclass
class ControlBinding:
    name: str
    label: str
    get: Callable[[], float]
    set: Callable[[Any], None]
    min: float = 0.0
    max: float = 1.0
    _control_id: str = field(init=False, default="")

    def _register(self, index: int) -> None:
        self._control_id = f"ctrl_{index}_{self.name}"

    def _control_spec(self) -> ControlSpec:
        return ControlSpec(
            id=self._control_id,
            label=self.label,
            value_spec=ScalarValueSpec(default=self.get(), min=self.min, max=self.max),
            send_to_backend=True,
        )

    def apply(self, backend: BackendBase, value: Any) -> bool:
        del backend
        self.set(value)
        return True


@dataclass
class ActionBinding:
    name: str
    label: str
    fn: Callable[[], None]
    resets_fields: bool = False
    _action_id: str = field(init=False, default="")

    def _register(self, index: int) -> None:
        self._action_id = f"action_{index}_{self.name}"

    def _action_spec(self) -> ActionSpec:
        return ActionSpec(id=self._action_id, label=self.label)


class TraceHandle:
    """User-facing reference to a registered trace."""

    __slots__ = ("_binding",)

    def __init__(self, binding: TraceBinding) -> None:
        self._binding = binding

    @property
    def name(self) -> str:
        return self._binding.name

    def sample(self) -> None:
        """Sample this trace now, skipping the auto-sample at end of tick."""
        self._binding._sample()


class ControlHandle:
    """User-facing reference to a registered control."""

    __slots__ = ("_binding",)

    def __init__(self, binding: ControlBinding) -> None:
        self._binding = binding

    @property
    def name(self) -> str:
        return self._binding.name


class ActionHandle:
    """User-facing reference to a registered action."""

    __slots__ = ("_binding",)

    def __init__(self, binding: ActionBinding) -> None:
        self._binding = binding

    @property
    def name(self) -> str:
        return self._binding.name


def append_bindings_to_app_spec(
    app_spec: AppSpec,
    *,
    traces: list[TraceBinding],
    controls: list[ControlBinding],
    actions: list[ActionBinding],
) -> AppSpec:
    """Add generic inline bindings to an AppSpec built by any backend."""

    fields = dict(app_spec.data.fields)
    geometries = dict(app_spec.data.geometries)
    views = dict(app_spec.view_catalog.views)
    operators = dict(app_spec.view_catalog.operators)
    controls_by_id = dict(app_spec.interactions.controls)
    actions_by_id = dict(app_spec.interactions.actions)
    layouts = dict(app_spec.layout_catalog.layouts)
    layout = layouts[app_spec.layout_catalog.active]
    panels = list(layout.panels)
    panel_grid = list(layout.panel_grid)
    panel_ids = {panel.id for panel in panels}

    for trace in traces:
        fields[trace._field_id] = trace._field_spec()
        views[trace._view_id] = trace._view_spec()

    for control in controls:
        controls_by_id[control._control_id] = control._control_spec()
    for action in actions:
        actions_by_id[action._action_id] = action._action_spec()

    for trace in traces:
        panel = trace._panel_spec()
        if panel.id not in panel_ids:
            panels.append(panel)
            panel_grid.append((panel.id,))
            panel_ids.add(panel.id)

    control_ids = tuple(control._control_id for control in controls)
    action_ids = tuple(action._action_id for action in actions)
    if control_ids or action_ids:
        controls_panel_index = next(
            (index for index, panel in enumerate(panels) if panel.kind == PANEL_KIND_CONTROLS),
            None,
        )
        if controls_panel_index is None:
            from compneurovis.core.app import PanelSpec

            controls_panel = PanelSpec(
                id="controls-panel",
                kind=PANEL_KIND_CONTROLS,
                control_ids=control_ids,
                action_ids=action_ids,
            )
            panels.append(controls_panel)
            panel_grid.append((controls_panel.id,))
        else:
            panel = panels[controls_panel_index]
            panels[controls_panel_index] = replace(
                panel,
                control_ids=tuple(dict.fromkeys((*panel.control_ids, *control_ids))),
                action_ids=tuple(dict.fromkeys((*panel.action_ids, *action_ids))),
            )

    layouts[app_spec.layout_catalog.active] = LayoutSpec(
        title=layout.title,
        panels=tuple(panels),
        panel_grid=tuple(panel_grid),
    )
    return AppSpec(
        data=DataCatalog(fields=fields, geometries=geometries),
        view_catalog=ViewCatalog(views=views, operators=operators),
        interactions=InteractionCatalog(controls=controls_by_id, actions=actions_by_id),
        layout_catalog=LayoutCatalog(
            layouts=layouts,
            active=app_spec.layout_catalog.active,
        ),
        metadata=app_spec.metadata,
    )


def emit_trace_updates(backend: BackendBase, traces: list[TraceBinding], *, auto_sample: bool = True) -> None:
    for trace in traces:
        if auto_sample and not trace._sampled_this_frame:
            trace._sample()
        msg = trace._drain_message()
        if msg is not None:
            backend.emit_update(msg.payload)


__all__ = [
    "ActionBinding",
    "ActionHandle",
    "ControlBinding",
    "ControlHandle",
    "SeriesReaders",
    "TraceBinding",
    "TraceHandle",
    "append_bindings_to_app_spec",
    "emit_trace_updates",
]
