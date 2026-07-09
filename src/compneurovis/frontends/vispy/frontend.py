from __future__ import annotations

import sys
import time
from dataclasses import replace
from typing import Any

import numpy as np
from PyQt6 import QtGui, QtWidgets
from PyQt6.QtCore import Qt
from vispy import use

use(app="pyqt6", gl="gl+")

from compneurovis.core._perf import perf_log
from compneurovis.core.runtime_options import env_int
from compneurovis.core import (
    ActionSpec,
    AppRef,
    app_ref,
    AppSpec,
    BarPlotViewSpec,
    ControlSpec,
    GridSliceOperatorSpec,
    LinePlotViewSpec,
    MorphologyGeometrySpec,
    MorphologyViewSpec,
    PanelSpec,
    StateGraphViewSpec,
    DEFAULT_FRAGMENT_ID,
)
from compneurovis.core.app_spec import (
    PANEL_KIND_BAR_PLOT,
    PANEL_KIND_CONTROLS,
    PANEL_KIND_LINE_PLOT,
    PANEL_KIND_STATE_GRAPH,
    PANEL_KIND_VIEW_3D,
)
from compneurovis.frontends.vispy.panels.controls import (
    ControlsHostPanel,
    ControlsPanel,
)
from compneurovis.frontends.vispy.panels.line_plot import (
    LinePlotHostPanel,
    LinePlotPanel,
)
from compneurovis.frontends.vispy.panels.state_graph import (
    StateGraphHostPanel,
    StateGraphPanel,
)
from compneurovis.frontends.vispy.panels.view3d import (
    IndependentCanvas3DHostPanel,
)
from compneurovis.core.projection import AppProjection
from compneurovis.frontends.base import FrontendBase
from compneurovis.frontends.vispy.view3d.viewport import Viewport3DPanel
from compneurovis.core.messages import (
    command_message,
    AppMetadataPatch,
    AppSpecDeclared,
    ControlPatch,
    EntityClicked,
    FieldAppend,
    FieldReplace,
    InvokeAction,
    KeyPressed,
    LayoutReplace,
    Message,
    MessagePayload,
    OperatorPatch,
    PanelPatch,
    Reset,
    RoutedMessage,
    Status,
    ValueChange,
    ViewPatch,
)
from compneurovis.frontends.vispy.interaction_context import FrontendInteractionContext
from compneurovis.frontends.vispy.interaction_target import resolve_interaction_target_source
from compneurovis.frontends.vispy.refresh_planning import (
    RefreshPlanner,
    RefreshTarget,
    _target_kind_counts,
    resolve_value,
)
from compneurovis.frontends.vispy.view_inputs.grid_slice import (
    field_from_grid_slice_operator,
)
from compneurovis.frontends.vispy.view3d.visuals import (
    MORPHOLOGY_3D_VISUAL_KEY,
    SURFACE_3D_VISUAL_KEY,
    View3DRefreshContext,
)
DEFAULT_LINE_PLOT_MAX_REFRESH_HZ = 15.0
DEFAULT_VIEW_3D_MAX_REFRESH_HZ = 8.0
DEFAULT_MAX_LINE_PLOT_REFRESHES_PER_FLUSH = 1
DEFAULT_MAX_VIEW_3D_REFRESHES_PER_FLUSH = env_int("CNV_MAX_VIEW_3D_REFRESHES_PER_FLUSH", 1, minimum=1)
DEFAULT_STATE_GRAPH_MAX_REFRESH_HZ = 15.0
DEFAULT_MAX_STATE_GRAPH_REFRESHES_PER_FLUSH = 1
HANDLE_MESSAGES_LOG_THRESHOLD_MS = 5.0
VIEW_3D_TARGET_KINDS = frozenset(
    {
        "morphology",
        "surface_visual",
        "surface_style",
        "surface_axes_geometry",
        "surface_axes_style",
        "operator_overlay",
    }
)

_KIND_TO_VISUAL_KEY: dict[str, str] = {
    "morphology":           MORPHOLOGY_3D_VISUAL_KEY,
    "surface_visual":       SURFACE_3D_VISUAL_KEY,
    "surface_style":        SURFACE_3D_VISUAL_KEY,
    "surface_axes_geometry": SURFACE_3D_VISUAL_KEY,
    "surface_axes_style":   SURFACE_3D_VISUAL_KEY,
    "operator_overlay":     SURFACE_3D_VISUAL_KEY,
}

_KIND_REFRESH_ORDER: dict[str, int] = {
    "morphology": 0,
    "surface_visual": 1,
    "surface_style": 2,
    "surface_axes_geometry": 3,
    "surface_axes_style": 4,
    "operator_overlay": 5,
}


def _coords_are_equal(left: dict[str, np.ndarray], right: dict[str, np.ndarray]) -> bool:
    if left.keys() != right.keys():
        return False
    return all(np.array_equal(np.asarray(left[key]), np.asarray(right[key])) for key in left)


def _update_type_counts(updates: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for update in updates:
        name = type(update).__name__
        counts[name] = counts.get(name, 0) + 1
    return counts


def _replace_message_payload(
    message: Message[MessagePayload],
    payload: MessagePayload,
) -> Message[MessagePayload]:
    return Message(type=message.type, intent=message.intent, payload=payload, tags=message.tags)


def _message_fragment_id(message: Message[MessagePayload]) -> str:
    return str(message.tags.get("fragment_id", DEFAULT_FRAGMENT_ID))


def _scoped_value_key(control: ControlSpec, fragment_id: str) -> AppRef:
    return app_ref(control.value_key or control.id, fragment_id=fragment_id)


def _scoped_control(control: ControlSpec, fragment_id: str) -> ControlSpec:
    return replace(
        control,
        id=app_ref(control.id, fragment_id=fragment_id),
        value_key=_scoped_value_key(control, fragment_id),
    )


def _command_ref(value: str | AppRef) -> tuple[str, dict[str, Any]]:
    ref = app_ref(value)
    return ref.id, {"fragment_id": ref.fragment_id}


class VispyFrontendWindow(QtWidgets.QMainWindow, FrontendBase):
    def __init__(self, *, title: str | None = None, interaction_target: Any = None):
        super().__init__()
        FrontendBase.__init__(self)
        self._title = title
        self.app_projection: AppProjection | None = None
        self.refresh_planner: RefreshPlanner | None = None
        self._active_selection_action_id: str | None = None
        if interaction_target is not None:
            self.interaction_target = resolve_interaction_target_source(interaction_target)
        else:
            self.interaction_target = None

        self.viewports: dict[str, Viewport3DPanel] = {}
        self.view_hosts: dict[str, IndependentCanvas3DHostPanel] = {}
        self._view_to_panel_id: dict[str, str] = {}
        self.line_plot_host_panels: dict[str, LinePlotHostPanel] = {}
        self.line_plot_panels: dict[str, LinePlotPanel] = {}
        self._dirty_line_plot_views: set[str] = set()
        self._line_plot_last_refresh_s: dict[str, float] = {}
        self._dirty_view_3d_targets: dict[str, set[str]] = {}
        self._view_3d_last_refresh_s: dict[str, float] = {}
        self._last_poll_started_s: float | None = None
        self.controls_host_panels: dict[str, ControlsHostPanel] = {}
        self.controls_panels: dict[str, ControlsPanel] = {}
        self.state_graph_host_panels: dict[str, StateGraphHostPanel] = {}
        self.state_graph_panels: dict[str, StateGraphPanel] = {}
        self._dirty_state_graph_views: set[str] = set()
        self._state_graph_last_refresh_s: dict[str, float] = {}

        self._layout_splitter: QtWidgets.QSplitter | None = None

        self._loading_label = QtWidgets.QLabel("Loading visualization...")
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._stack = QtWidgets.QStackedWidget(self)
        self._stack.addWidget(self._loading_label)

        self.setCentralWidget(self._stack)
        self.resize(1280, 720)
        self.statusBar().showMessage("Starting CompNeuroVis")
        self._show_loading_state()

    def initialize(self, app_spec: AppSpec | None) -> None:
        # Some launch paths declare AppSpec over the runtime channel instead
        # of passing it directly at construction time. Start in the loading
        # state and adopt AppSpecDeclared on arrival.
        if app_spec is None:
            self._show_loading_state()
            return
        self._set_app_spec(app_spec)

    def render(self) -> None:
        self.update()

    def shutdown(self) -> None:
        pass

    def paintEvent(self, event) -> None:
        started = time.monotonic()
        super().paintEvent(event)
        duration_ms = round((time.monotonic() - started) * 1000.0, 3)
        if duration_ms >= 5.0:
            perf_log(
                "frontend",
                "window_paint",
                width_px=self.width(),
                height_px=self.height(),
                duration_ms=duration_ms,
            )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        perf_log(
            "frontend",
            "window_resize",
            width_px=self.width(),
            height_px=self.height(),
        )

    @property
    def viewport(self) -> Viewport3DPanel | None:
        return next(iter(self.viewports.values()), None)

    def line_plot_panel(self, view_id: str | AppRef) -> LinePlotPanel | None:
        panel_id = self._view_to_panel_id.get(view_id) or self._view_to_panel_id.get(app_ref(view_id))
        if panel_id is None:
            return None
        return self.line_plot_panels.get(panel_id)

    def controls_panel(self, panel_id: str) -> ControlsPanel | None:
        return self.controls_panels.get(panel_id)

    def viewport_for(self, view_id: str | AppRef) -> Viewport3DPanel | None:
        return self.viewports.get(view_id) or self.viewports.get(app_ref(view_id))

    def _show_loading_state(self, message: str = "Loading visualization...") -> None:
        self._loading_label.setText(message)
        self._stack.setCurrentWidget(self._loading_label)

    def _show_content_state(self) -> None:
        if self._layout_splitter is not None:
            self._stack.setCurrentWidget(self._layout_splitter)

    @property
    def app_spec(self) -> AppSpec | None:
        """Read-only view of this actor's projected app structure.

        The frontend folds the runtime stream into an actor-local
        AppProjection. All read sites use this property; mutations go through
        the projection, not the startup AppSpec declaration.
        """
        return self.app_projection.spec if self.app_projection is not None else None

    def _field(
        self,
        field_id: str | AppRef | None,
        *,
        fragment_id: str = DEFAULT_FRAGMENT_ID,
    ) -> Field | None:
        """The materialized Field for an id, resolved through AppProjection."""
        if not field_id or self.app_projection is None:
            return None
        return self.app_projection.field(field_id, fragment_id=fragment_id)

    def value_snapshot(self) -> dict[Any, Any]:
        """Snapshot of frontend-owned values for resolver and panel APIs."""
        return self.values.snapshot()

    def _values_for_fragment(self, fragment_id: str) -> dict[Any, Any]:
        values = self.value_snapshot()
        for key, value in tuple(values.items()):
            if isinstance(key, AppRef) and key.fragment_id == fragment_id:
                values[key.id] = value
        return values

    def _bind_frontend_value(self, value_key: str | AppRef, initial: Any) -> None:
        self.values.bind(
            value_key,
            lambda actor, value, _value_key=value_key: actor._set_frontend_value(_value_key, value),
            initial=initial,
        )

    def _set_frontend_value(self, value_key: str | AppRef, value: Any) -> None:
        self.values.set(value_key, value)

    def _apply_frontend_value(self, value_key: str | AppRef, value: Any) -> None:
        acted = self.values.apply(self, {value_key: value})
        if not acted:
            self.values.set(value_key, value)

    def _active_layout(self):
        """The live active LayoutSpec — resolved via AppProjection, not the blueprint default."""
        return self.app_projection.active_layout() if self.app_projection is not None else None

    def _set_app_spec(self, app_spec: AppSpec) -> None:
        started = time.monotonic()
        self.app_projection = AppProjection(app_spec)
        app_spec = self.app_projection.spec
        self.refresh_planner = RefreshPlanner(app_spec, self.app_projection.active_layout)
        self._active_selection_action_id = None
        self.setWindowTitle(self._title or self._active_layout().title)
        for control_ref, control in app_spec.iter_controls():
            value_key = _scoped_value_key(control, control_ref.fragment_id)
            initial_value = self.values.get(value_key, control.default_value())
            self._bind_frontend_value(value_key, initial_value)

        rebuild_started = time.monotonic()
        self._rebuild_panels()
        rebuild_ms = round((time.monotonic() - rebuild_started) * 1000.0, 3)

        refresh_started = time.monotonic()
        self._update_panel_visibility()
        self._apply_refresh_targets(
            self.refresh_planner.full_refresh_targets(),
            force_line_plots=True,
            force_view_3d=True,
            force_state_graph=True,
        )
        full_refresh_ms = round((time.monotonic() - refresh_started) * 1000.0, 3)
        self._show_content_state()
        perf_log(
            "frontend",
            "set_app_spec",
            view_count=sum(1 for _ in app_spec.iter_view_specs()),
            field_count=sum(1 for _ in app_spec.iter_field_specs()),
            geometry_count=sum(1 for _ in app_spec.iter_geometry_specs()),
            panel_count=len(self._active_layout().panels),
            rebuild_panels_ms=rebuild_ms,
            full_refresh_ms=full_refresh_ms,
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )

    def _view_ids_in_3d_panels(self) -> tuple[str, ...]:
        if self.app_spec is None:
            return ()
        return tuple(
            view_id
            for panel in self._active_layout().panels_of_kind(PANEL_KIND_VIEW_3D)
            for view_id in panel.view_ids
        )

    def _create_view_host(self, panel: PanelSpec):
        if panel.host_kind != "independent_canvas":
            raise ValueError(f"Unsupported 3D host kind '{panel.host_kind}'")
        if len(panel.view_ids) != 1:
            raise ValueError(
                f"3D panel '{panel.id}' with host_kind='independent_canvas' must contain exactly one view id"
            )
        view_id = panel.view_ids[0]
        return IndependentCanvas3DHostPanel(
            panel=panel,
            title=panel.title or str(view_id),
            on_entity_selected=self._on_entity_selected,
        )

    def _rebuild_panels(self) -> None:
        started = time.monotonic()
        self.viewports.clear()
        self.view_hosts.clear()
        self._view_to_panel_id.clear()
        self.line_plot_host_panels.clear()
        self.line_plot_panels.clear()
        self._dirty_line_plot_views.clear()
        self._line_plot_last_refresh_s.clear()
        self._dirty_view_3d_targets.clear()
        self._view_3d_last_refresh_s.clear()
        self.controls_host_panels.clear()
        self.controls_panels.clear()
        self.state_graph_host_panels.clear()
        self.state_graph_panels.clear()
        self._dirty_state_graph_views.clear()
        self._state_graph_last_refresh_s.clear()

        if self._layout_splitter is not None:
            idx = self._stack.indexOf(self._layout_splitter)
            if idx >= 0:
                self._stack.removeWidget(self._layout_splitter)
            self._layout_splitter.deleteLater()
            self._layout_splitter = None

        outer = QtWidgets.QSplitter(Qt.Orientation.Vertical)
        outer.setChildrenCollapsible(False)
        outer.setOpaqueResize(False)
        self._layout_splitter = outer

        for row_cells in self._resolved_panel_grid():
            if len(row_cells) == 1:
                cell = row_cells[0]
                widget = self._make_panel_for_cell(cell)
                if widget is not None:
                    outer.addWidget(widget)
            else:
                row = QtWidgets.QSplitter(Qt.Orientation.Horizontal)
                row.setChildrenCollapsible(False)
                row.setOpaqueResize(False)
                for cell in row_cells:
                    widget = self._make_panel_for_cell(cell)
                    if widget is not None:
                        row.addWidget(widget)
                outer.addWidget(row)

        self._stack.addWidget(outer)
        perf_log(
            "frontend",
            "rebuild_panels",
            row_count=outer.count(),
            view_host_count=len(self.view_hosts),
            line_plot_host_count=len(self.line_plot_host_panels),
            controls_host_count=len(self.controls_host_panels),
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )

    def _resolved_panel_grid(self) -> tuple[tuple[str, ...], ...]:
        if self.app_spec is None:
            return ()
        return self._active_layout().panel_grid

    def _make_panel_for_cell(self, cell_id: str) -> QtWidgets.QWidget | None:
        started = time.monotonic()
        if self.app_spec is None:
            return None
        panel_spec = self._active_layout().panel(cell_id)
        if panel_spec is None:
            return None
        if panel_spec.kind in (PANEL_KIND_LINE_PLOT, PANEL_KIND_BAR_PLOT):
            view_id = panel_spec.view_ids[0]
            host = LinePlotHostPanel(
                panel_id=panel_spec.id,
                view_id=view_id,
                title=panel_spec.title,
                show_internal_title=True,
            )
            self.line_plot_host_panels[panel_spec.id] = host
            self.line_plot_panels[panel_spec.id] = host.line_plot_panel
            self._view_to_panel_id[view_id] = panel_spec.id
            perf_log(
                "frontend",
                "create_panel",
                panel_id=panel_spec.id,
                panel_kind=panel_spec.kind,
                view_ids=panel_spec.view_ids,
                duration_ms=round((time.monotonic() - started) * 1000.0, 3),
            )
            return host
        if panel_spec.kind == PANEL_KIND_VIEW_3D:
            panel = self._create_view_host(panel_spec)
            self.view_hosts[panel_spec.id] = panel
            for view_id in panel_spec.view_ids:
                self.viewports[view_id] = panel.viewport
                self._view_to_panel_id[view_id] = panel_spec.id
            perf_log(
                "frontend",
                "create_panel",
                panel_id=panel_spec.id,
                panel_kind=panel_spec.kind,
                view_ids=panel_spec.view_ids,
                duration_ms=round((time.monotonic() - started) * 1000.0, 3),
            )
            return panel
        if panel_spec.kind == PANEL_KIND_CONTROLS:
            controls_panel = ControlsPanel(self._on_control_changed, self._on_action_invoked)
            title = panel_spec.title or "Controls"
            host = ControlsHostPanel(controls_panel, panel_id=panel_spec.id, title=title)
            self.controls_host_panels[panel_spec.id] = host
            self.controls_panels[panel_spec.id] = controls_panel
            perf_log(
                "frontend",
                "create_panel",
                panel_id=panel_spec.id,
                panel_kind=panel_spec.kind,
                duration_ms=round((time.monotonic() - started) * 1000.0, 3),
            )
            return host
        if panel_spec.kind == PANEL_KIND_STATE_GRAPH:
            view_id = panel_spec.view_ids[0]
            title = panel_spec.title or str(view_id)
            host = StateGraphHostPanel(panel_id=panel_spec.id, view_id=view_id, title=title)
            self.state_graph_host_panels[panel_spec.id] = host
            self.state_graph_panels[panel_spec.id] = host.state_graph_panel
            self._view_to_panel_id[view_id] = panel_spec.id
            perf_log(
                "frontend",
                "create_panel",
                panel_id=panel_spec.id,
                panel_kind=panel_spec.kind,
                view_ids=panel_spec.view_ids,
                duration_ms=round((time.monotonic() - started) * 1000.0, 3),
            )
            return host
        return None

    def _line_view(self, view_id: str | AppRef):
        if self.app_spec is None:
            return None
        view = self.app_spec.view(view_id)
        return view if isinstance(view, (LinePlotViewSpec, BarPlotViewSpec)) else None

    def _refresh_priority_key(self, view_id: str | AppRef, last_refresh_s: dict[Any, float]) -> tuple[float, str]:
        last = last_refresh_s.get(view_id)
        return (float("-inf") if last is None else last, str(view_id))

    def _view_host(self, view_id: str):
        panel_id = self._view_to_panel_id.get(view_id)
        if panel_id is None:
            return None
        return self.view_hosts.get(panel_id)

    def _resolved_controls_and_actions(self, panel_id: str) -> tuple[list[ControlSpec], list[ActionSpec]]:
        if self.app_spec is None:
            return [], []
        panel = self._active_layout().panel(panel_id)
        if panel is None or panel.kind != PANEL_KIND_CONTROLS:
            return [], []
        controls: list[ControlSpec] = []
        for control_id in panel.control_ids:
            control_ref = app_ref(control_id)
            control = self.app_spec.control(control_ref)
            if control is not None:
                controls.append(_scoped_control(control, control_ref.fragment_id))
        actions: list[ActionSpec] = []
        for action_id in panel.action_ids:
            action_ref = app_ref(action_id)
            action = self.app_spec.action(action_ref)
            if action is not None:
                actions.append(replace(action, id=action_ref))
        return controls, actions

    def _update_panel_visibility(self) -> None:
        for panel_id, host in self.controls_host_panels.items():
            controls, actions = self._resolved_controls_and_actions(panel_id)
            host.setVisible(bool(controls or actions))
        self._apply_panel_sizes()

    def _apply_panel_sizes(self) -> None:
        if self._layout_splitter is None:
            return
        width = max(self.width(), 1)
        height = max(self.height(), 1)
        n_rows = self._layout_splitter.count()
        if n_rows == 0:
            return
        last_is_controls = isinstance(self._layout_splitter.widget(n_rows - 1), ControlsHostPanel)
        if last_is_controls and n_rows > 1:
            ctrl_h = min(max(140, int(height * 0.28)), max(140, int(height * 0.45)))
            view_h = max(1, int((height - ctrl_h) / (n_rows - 1)))
            sizes = [view_h] * (n_rows - 1) + [ctrl_h]
        else:
            row_h = max(1, int(height / n_rows))
            sizes = [row_h] * n_rows
        self._layout_splitter.setSizes(sizes)
        for i in range(n_rows):
            row_widget = self._layout_splitter.widget(i)
            if isinstance(row_widget, QtWidgets.QSplitter):
                n_cols = row_widget.count()
                if n_cols:
                    row_widget.setSizes([max(1, int(width / n_cols))] * n_cols)

    def _refresh_controls(self) -> None:
        if self.app_spec is None:
            return
        for panel_id, host in self.controls_host_panels.items():
            controls, actions = self._resolved_controls_and_actions(panel_id)
            host.set_section_title(has_controls=bool(controls), has_actions=bool(actions))
            panel = self.controls_panels.get(panel_id)
            if panel is not None:
                panel.set_controls(controls, actions, self.value_snapshot())

    def _refresh_line_plot(self, view_id: str) -> None:
        self._refresh_line_plot_if_due(view_id, force=True)

    def _state_graph_view(self, view_id: str | AppRef):
        if self.app_spec is None:
            return None
        view = self.app_spec.view(view_id)
        return view if isinstance(view, StateGraphViewSpec) else None

    def _state_graph_refresh_interval_s(self, view_id: str) -> float | None:
        view = self._state_graph_view(view_id)
        if view is None:
            return None
        max_hz = view.max_refresh_hz if view.max_refresh_hz is not None else DEFAULT_STATE_GRAPH_MAX_REFRESH_HZ
        if float(max_hz) <= 0:
            return None
        return 1.0 / float(max_hz)

    def _refresh_state_graph(self, view_id: str) -> None:
        self._refresh_state_graph_if_due(view_id, force=True)

    def _refresh_state_graph_if_due(
        self,
        view_id: str,
        *,
        force: bool = False,
        now: float | None = None,
    ) -> bool:
        if self.app_spec is None:
            self._dirty_state_graph_views.discard(view_id)
            return False
        panel_id = self._view_to_panel_id.get(view_id)
        if panel_id is None:
            self._dirty_state_graph_views.discard(view_id)
            return False
        host = self.state_graph_host_panels.get(panel_id)
        if host is None:
            self._dirty_state_graph_views.discard(view_id)
            return False
        current_time = time.monotonic() if now is None else now
        if not force:
            interval = self._state_graph_refresh_interval_s(view_id)
            last = self._state_graph_last_refresh_s.get(view_id)
            if interval is not None and last is not None and current_time - last < interval:
                self._dirty_state_graph_views.add(view_id)
                return False
        state_graph_view = self._state_graph_view(view_id)
        node_field = None
        edge_field = None
        if state_graph_view is not None:
            view_ref = app_ref(view_id)
            if state_graph_view.node_field_id:
                node_field = self._field(state_graph_view.node_field_id, fragment_id=view_ref.fragment_id)
            if state_graph_view.edge_field_id:
                edge_field = self._field(state_graph_view.edge_field_id, fragment_id=view_ref.fragment_id)
        host.refresh(state_graph_view, node_field, edge_field)
        self._state_graph_last_refresh_s[view_id] = current_time
        self._dirty_state_graph_views.discard(view_id)
        return True

    def _flush_due_state_graph_refreshes(
        self,
        *,
        force: bool = False,
        now: float | None = None,
        refresh_deadline_s: float | None = None,
    ) -> tuple[int, int]:
        if not self._dirty_state_graph_views:
            return 0, 0
        current_time = time.monotonic() if now is None else now
        refreshed = 0
        refresh_limit = None if force else DEFAULT_MAX_STATE_GRAPH_REFRESHES_PER_FLUSH
        for view_id in sorted(
            tuple(self._dirty_state_graph_views),
            key=lambda vid: self._refresh_priority_key(vid, self._state_graph_last_refresh_s),
        ):
            if refresh_limit is not None and refreshed >= refresh_limit:
                break
            if refresh_deadline_s is not None and refreshed > 0 and time.monotonic() >= refresh_deadline_s:
                break
            refreshed += int(self._refresh_state_graph_if_due(view_id, force=force, now=current_time))
        return refreshed, len(self._dirty_state_graph_views)

    def _line_plot_refresh_interval_s(self, view_id: str) -> float | None:
        view = self._line_view(view_id)
        if view is None:
            return None
        max_refresh_hz = view.max_refresh_hz
        if max_refresh_hz is None:
            max_refresh_hz = DEFAULT_LINE_PLOT_MAX_REFRESH_HZ
        max_refresh_hz = float(max_refresh_hz)
        if max_refresh_hz <= 0:
            return None
        return 1.0 / max_refresh_hz

    def _view_3d_refresh_interval_s(self, view_id: str) -> float | None:
        if self.app_spec is None:
            return None
        view = self.app_spec.view(view_id)
        if view is None:
            return None
        hz = getattr(view, "max_refresh_hz", None)
        max_refresh_hz = float(DEFAULT_VIEW_3D_MAX_REFRESH_HZ if hz is None else hz)
        if max_refresh_hz <= 0:
            return None
        return 1.0 / max_refresh_hz

    def _refresh_line_plot_if_due(
        self,
        view_id: str,
        *,
        force: bool = False,
        now: float | None = None,
    ) -> bool:
        if self.app_spec is None:
            self._dirty_line_plot_views.discard(view_id)
            return False
        panel_id = self._view_to_panel_id.get(view_id)
        if panel_id is None:
            self._dirty_line_plot_views.discard(view_id)
            return False
        host = self.line_plot_host_panels.get(panel_id)
        if host is None:
            self._dirty_line_plot_views.discard(view_id)
            return False
        current_time = time.monotonic() if now is None else now
        if not force:
            interval = self._line_plot_refresh_interval_s(view_id)
            last_refresh = self._line_plot_last_refresh_s.get(view_id)
            if interval is not None and last_refresh is not None and current_time - last_refresh < interval:
                self._dirty_line_plot_views.add(view_id)
                return False
        line_view = self._line_view(view_id)
        line_field = None
        view_ref = app_ref(view_id)
        view_values = self._values_for_fragment(view_ref.fragment_id)
        if line_view is not None:
            operator_id = getattr(line_view, "operator_id", None)
            if operator_id is not None:
                operator_ref = app_ref(operator_id, fragment_id=view_ref.fragment_id)
                operator = self.app_spec.operator(operator_ref)
                if isinstance(operator, GridSliceOperatorSpec):
                    source_field = self._field(operator.field_id, fragment_id=operator_ref.fragment_id)
                    if source_field is not None:
                        line_field = field_from_grid_slice_operator(source_field, operator, view_values)
            else:
                line_field = self._field(line_view.field_id, fragment_id=view_ref.fragment_id)
        host.refresh(line_view, line_field, view_values)
        self._line_plot_last_refresh_s[view_id] = current_time
        self._dirty_line_plot_views.discard(view_id)
        return True

    def _refresh_view_3d_if_due(
        self,
        view_id: str,
        *,
        force: bool = False,
        now: float | None = None,
    ) -> bool:
        if self.app_spec is None:
            self._dirty_view_3d_targets.pop(view_id, None)
            return False
        host = self._view_host(view_id)
        if host is None:
            self._dirty_view_3d_targets.pop(view_id, None)
            return False
        current_time = time.monotonic() if now is None else now
        if not force:
            interval = self._view_3d_refresh_interval_s(view_id)
            last_refresh = self._view_3d_last_refresh_s.get(view_id)
            if interval is not None and last_refresh is not None and current_time - last_refresh < interval:
                return False
        pending_kinds = self._dirty_view_3d_targets.get(view_id)
        if not pending_kinds:
            self._dirty_view_3d_targets.pop(view_id, None)
            return False
        view = self.app_spec.view(view_id)
        ctx = View3DRefreshContext(
            app_spec=self.app_spec,
            values=self.value_snapshot(),
            view_id=view_id,
            fields=self.app_projection.fields,
            active_layout=self._active_layout(),
        )
        for kind in sorted(tuple(pending_kinds), key=lambda k: _KIND_REFRESH_ORDER.get(k, 99)):
            visual_key = _KIND_TO_VISUAL_KEY.get(kind)
            if visual_key is None:
                continue
            selectable = bool(view.selectable) if isinstance(view, MorphologyViewSpec) else False
            visual = host.activate_visual(view_id, visual_key, selectable=selectable)
            if visual is not None:
                visual.refresh_for_target(kind, view, ctx)
        if view is not None:
            host.set_background(resolve_value(getattr(view, "background_color", "white"), self.value_snapshot(), app_ref(view_id).fragment_id))
        if isinstance(view, MorphologyViewSpec):
            self._refresh_morphology_colorbar(host, view, app_ref(view_id).fragment_id)
        else:
            host.clear_colorbar()
        host.commit()
        self._view_3d_last_refresh_s[view_id] = current_time
        self._dirty_view_3d_targets.pop(view_id, None)
        return True

    def _refresh_morphology_colorbar(self, host: IndependentCanvas3DHostPanel, view: MorphologyViewSpec, fragment_id: str) -> None:
        if self.app_projection is None or not view.color_field_id:
            host.clear_colorbar()
            return
        field = self._field(view.color_field_id, fragment_id=fragment_id)
        if field is None:
            host.clear_colorbar()
            return
        if view.sample_dim and view.sample_dim in field.dims:
            values = field.select({view.sample_dim: -1}).values
        else:
            values = field.values
        values = np.asarray(values, dtype=np.float32)
        finite = values[np.isfinite(values)]
        if finite.size == 0:
            host.clear_colorbar()
            return
        limits = resolve_value(view.color_limits, self.value_snapshot(), fragment_id)
        if limits is None:
            limits = field.attrs.get("color_limits")
        if limits is None:
            vmin = float(np.min(finite))
            vmax = float(np.max(finite))
        else:
            vmin = float(limits[0])
            vmax = float(limits[1])
        variable = str(field.attrs.get("variable", "")).strip()
        unit_value = field.attrs.get("unit", field.unit)
        unit = "" if unit_value is None else str(unit_value).strip()
        label = variable or field.id
        if unit:
            label = f"{label} ({unit})"
        host.set_colorbar(color_map=str(view.color_map), vmin=vmin, vmax=vmax, label=label)

    def _flush_due_line_plot_refreshes(
        self,
        *,
        force: bool = False,
        now: float | None = None,
        refresh_deadline_s: float | None = None,
    ) -> tuple[int, int]:
        if not self._dirty_line_plot_views:
            return 0, 0
        current_time = time.monotonic() if now is None else now
        refreshed = 0
        refresh_limit = None if force else DEFAULT_MAX_LINE_PLOT_REFRESHES_PER_FLUSH
        for view_id in sorted(
            tuple(self._dirty_line_plot_views),
            key=lambda dirty_view_id: self._refresh_priority_key(dirty_view_id, self._line_plot_last_refresh_s),
        ):
            if refresh_limit is not None and refreshed >= refresh_limit:
                break
            if refresh_deadline_s is not None and refreshed > 0 and time.monotonic() >= refresh_deadline_s:
                break
            refreshed += int(self._refresh_line_plot_if_due(view_id, force=force, now=current_time))
        return refreshed, len(self._dirty_line_plot_views)

    def _flush_due_view_3d_refreshes(
        self,
        *,
        force: bool = False,
        now: float | None = None,
        refresh_deadline_s: float | None = None,
    ) -> tuple[int, int]:
        if not self._dirty_view_3d_targets:
            return 0, 0
        current_time = time.monotonic() if now is None else now
        refreshed = 0
        refresh_limit = None if force else DEFAULT_MAX_VIEW_3D_REFRESHES_PER_FLUSH
        for view_id in sorted(
            tuple(self._dirty_view_3d_targets),
            key=lambda dirty_view_id: self._refresh_priority_key(dirty_view_id, self._view_3d_last_refresh_s),
        ):
            if refresh_limit is not None and refreshed >= refresh_limit:
                break
            if refresh_deadline_s is not None and refreshed > 0 and time.monotonic() >= refresh_deadline_s:
                break
            refreshed += int(self._refresh_view_3d_if_due(view_id, force=force, now=current_time))
        return refreshed, len(self._dirty_view_3d_targets)

    def _apply_refresh_targets(
        self,
        targets: set[RefreshTarget],
        *,
        force_line_plots: bool = False,
        force_view_3d: bool = False,
        force_state_graph: bool = False,
        refresh_deadline_s: float | None = None,
    ) -> None:
        if not targets:
            return
        started = time.monotonic()

        if RefreshTarget.CONTROLS in targets:
            self._refresh_controls()

        line_plot_target_count = 0
        for target in sorted(
            (target for target in targets if target.kind == "line_plot" and target.view_id is not None),
            key=lambda target: str(target.view_id or ""),
        ):
            self._dirty_line_plot_views.add(target.view_id)
            line_plot_target_count += 1
        view_3d_target_count = 0
        for target in sorted(
            (target for target in targets if target.kind in VIEW_3D_TARGET_KINDS and target.view_id is not None),
            key=lambda target: (str(target.view_id or ""), target.kind),
        ):
            self._dirty_view_3d_targets.setdefault(target.view_id, set()).add(target.kind)
            view_3d_target_count += 1
        state_graph_target_count = 0
        for target in sorted(
            (target for target in targets if target.kind == "state_graph" and target.view_id is not None),
            key=lambda target: str(target.view_id or ""),
        ):
            self._dirty_state_graph_views.add(target.view_id)
            state_graph_target_count += 1

        line_plot_refreshed_count, line_plot_deferred_count = self._flush_due_line_plot_refreshes(
            force=force_line_plots,
            now=started,
            refresh_deadline_s=refresh_deadline_s,
        )
        if refresh_deadline_s is None or time.monotonic() < refresh_deadline_s:
            view_3d_refreshed_count, view_3d_deferred_count = self._flush_due_view_3d_refreshes(
                force=force_view_3d,
                now=started,
                refresh_deadline_s=refresh_deadline_s,
            )
        else:
            view_3d_refreshed_count = 0
            view_3d_deferred_count = len(self._dirty_view_3d_targets)
        if refresh_deadline_s is None or time.monotonic() < refresh_deadline_s:
            state_graph_refreshed_count, state_graph_deferred_count = self._flush_due_state_graph_refreshes(
                force=force_state_graph,
                now=started,
                refresh_deadline_s=refresh_deadline_s,
            )
        else:
            state_graph_refreshed_count = 0
            state_graph_deferred_count = len(self._dirty_state_graph_views)
        perf_log(
            "frontend",
            "apply_refresh_targets",
            target_count=len(targets),
            target_kinds=_target_kind_counts(targets),
            line_plot_target_count=line_plot_target_count,
            line_plot_refreshed_count=line_plot_refreshed_count,
            line_plot_deferred_count=line_plot_deferred_count,
            view_3d_target_count=view_3d_target_count,
            view_3d_refreshed_count=view_3d_refreshed_count,
            view_3d_deferred_count=view_3d_deferred_count,
            dirty_view_3d_count=len(self._dirty_view_3d_targets),
            state_graph_target_count=state_graph_target_count,
            state_graph_refreshed_count=state_graph_refreshed_count,
            state_graph_deferred_count=state_graph_deferred_count,
            dirty_state_graph_count=len(self._dirty_state_graph_views),
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )

    def flush_due_refreshes(self, *, now: float, refresh_deadline_s: float | None = None) -> None:
        if self._dirty_line_plot_views:
            self._flush_due_line_plot_refreshes(now=now, refresh_deadline_s=refresh_deadline_s)
        if self._dirty_view_3d_targets and (refresh_deadline_s is None or time.monotonic() < refresh_deadline_s):
            self._flush_due_view_3d_refreshes(now=now, refresh_deadline_s=refresh_deadline_s)
        if self._dirty_state_graph_views and (refresh_deadline_s is None or time.monotonic() < refresh_deadline_s):
            self._flush_due_state_graph_refreshes(now=now, refresh_deadline_s=refresh_deadline_s)

    def handle(self, message: Message[MessagePayload]) -> None:
        self._handle_update_messages([message], poll_started=time.monotonic(), timer_gap_ms=None)

    def compact_update_messages(self, messages: list[Message[MessagePayload]]) -> list[Message[MessagePayload]]:
        """Coalesce stale visual updates before applying a frontend backlog."""

        if not messages or self.app_projection is None:
            return messages
        if any(isinstance(message.payload, AppSpecDeclared) for message in messages):
            return messages

        compacted: list[Message[MessagePayload]] = []
        pending: dict[AppRef, dict[str, Message[MessagePayload] | None]] = {}
        pending_order: list[AppRef] = []
        dropped_field_replace_count = 0
        merged_field_append_count = 0

        def field_ref_for(message: Message[MessagePayload], field_id: str) -> AppRef:
            return app_ref(field_id, fragment_id=_message_fragment_id(message))

        def ensure_field(field_ref: AppRef) -> dict[str, Message[MessagePayload] | None]:
            if field_ref not in pending:
                pending[field_ref] = {"replace": None, "append": None}
                pending_order.append(field_ref)
            return pending[field_ref]

        def flush_field(field_ref: AppRef) -> None:
            slot = pending.pop(field_ref, None)
            if slot is None:
                return
            replace_message = slot.get("replace")
            append_message = slot.get("append")
            if replace_message is not None:
                compacted.append(replace_message)
            if append_message is not None:
                compacted.append(append_message)
            try:
                pending_order.remove(field_ref)
            except ValueError:
                pass

        def flush_pending() -> None:
            for field_ref in tuple(pending_order):
                flush_field(field_ref)

        for message in messages:
            update = message.payload
            if isinstance(update, FieldReplace):
                field_ref = field_ref_for(message, update.field_id)
                slot = ensure_field(field_ref)
                previous = slot.get("replace")
                if previous is not None and isinstance(previous.payload, FieldReplace):
                    dropped_field_replace_count += 1
                    attrs_update = {**previous.payload.attrs_update, **update.attrs_update}
                    coords = update.coords if update.coords is not None else previous.payload.coords
                    update = FieldReplace(
                        field_id=update.field_id,
                        values=update.values,
                        coords=coords,
                        attrs_update=attrs_update,
                    )
                    message = _replace_message_payload(message, update)
                slot["replace"] = message
                slot["append"] = None
                continue
            if isinstance(update, FieldAppend):
                field_ref = field_ref_for(message, update.field_id)
                slot = ensure_field(field_ref)
                previous = slot.get("append")
                if previous is None:
                    slot["append"] = self._trim_field_append_message(message)
                    continue
                merged = self._merge_field_append_messages(previous, message)
                if merged is None:
                    flush_field(field_ref)
                    ensure_field(field_ref)["append"] = self._trim_field_append_message(message)
                else:
                    merged_field_append_count += 1
                    slot["append"] = merged
                continue

            flush_pending()
            compacted.append(message)

        flush_pending()
        if len(compacted) != len(messages):
            perf_log(
                "frontend",
                "compact_update_messages",
                before_count=len(messages),
                after_count=len(compacted),
                dropped_field_replace_count=dropped_field_replace_count,
                merged_field_append_count=merged_field_append_count,
                update_types_before=_update_type_counts([message.payload for message in messages]),
                update_types_after=_update_type_counts([message.payload for message in compacted]),
            )
        return compacted

    def _merge_field_append_messages(
        self,
        left_message: Message[MessagePayload],
        right_message: Message[MessagePayload],
    ) -> Message[MessagePayload] | None:
        left = left_message.payload
        right = right_message.payload
        if not isinstance(left, FieldAppend) or not isinstance(right, FieldAppend):
            return None
        if _message_fragment_id(left_message) != _message_fragment_id(right_message):
            return None
        if (
            left.field_id != right.field_id
            or left.append_dim != right.append_dim
            or left.max_length != right.max_length
        ):
            return None
        field_ref = app_ref(left.field_id, fragment_id=_message_fragment_id(left_message))
        field = self.app_projection.field(field_ref) if self.app_projection is not None else None
        if field is None:
            return None
        try:
            axis = field.axis_index(left.append_dim)
            merged = FieldAppend(
                field_id=left.field_id,
                append_dim=left.append_dim,
                values=np.concatenate([left.values, right.values], axis=axis),
                coord_values=np.concatenate([left.coord_values, right.coord_values], axis=0),
                max_length=right.max_length,
                attrs_update={**left.attrs_update, **right.attrs_update},
            )
        except Exception:
            return None
        return self._trim_field_append_message(_replace_message_payload(right_message, merged))

    def _trim_field_append_message(
        self,
        message: Message[MessagePayload],
    ) -> Message[MessagePayload]:
        update = message.payload
        if not isinstance(update, FieldAppend):
            return message
        trimmed = self._trim_field_append(update, fragment_id=_message_fragment_id(message))
        if trimmed is update:
            return message
        return _replace_message_payload(message, trimmed)

    def _trim_field_append(self, update: FieldAppend, *, fragment_id: str) -> FieldAppend:
        if update.max_length is None or update.max_length < 0:
            return update
        max_length = int(update.max_length)
        if len(update.coord_values) <= max_length:
            return update
        field = self._field(update.field_id, fragment_id=fragment_id)
        if field is None:
            return update
        axis = field.axis_index(update.append_dim)
        slicers = [slice(None)] * np.asarray(update.values).ndim
        slicers[axis] = slice(0, 0) if max_length == 0 else slice(-max_length, None)
        return FieldAppend(
            field_id=update.field_id,
            append_dim=update.append_dim,
            values=np.asarray(update.values)[tuple(slicers)],
            coord_values=np.asarray(update.coord_values)[:0] if max_length == 0 else np.asarray(update.coord_values)[-max_length:],
            max_length=update.max_length,
            attrs_update=update.attrs_update,
        )

    def _emit_command(self, command: MessagePayload, *, tags: dict[str, Any] | None = None) -> None:
        self.emit(command_message(command, tags=tags))

    def _handle_update_messages(
        self,
        messages: list[Message[MessagePayload]],
        *,
        poll_started: float,
        timer_gap_ms: float | None,
        refresh_deadline_s: float | None = None,
    ) -> None:
        handle_started = time.monotonic()
        pending_targets: set[RefreshTarget] = set()
        pending_status: str | None = None
        pending_field_appends: dict[AppRef, FieldAppend] = {}
        flushed_field_appends = 0
        appended_samples_by_field: dict[str, int] = {}
        field_append_apply_ms = 0.0
        field_replace_apply_ms = 0.0
        field_replace_count = 0
        refresh_apply_ms = 0.0
        updates = [message.payload for message in messages]

        for message in messages:
            update = message.payload
            if isinstance(update, AppSpecDeclared) and self.app_projection is None:
                self._set_app_spec(update.app_spec)

        def flush_pending_field_appends() -> None:
            nonlocal pending_targets, flushed_field_appends, field_append_apply_ms
            if not pending_field_appends:
                return
            if self.app_spec is None:
                pending_field_appends.clear()
                return
            for field_ref, update in pending_field_appends.items():
                append_started = time.monotonic()
                flushed_field_appends += 1
                field_key = str(field_ref)
                appended_samples_by_field[field_key] = appended_samples_by_field.get(field_key, 0) + int(len(update.coord_values))
                current = self.app_projection.fields[field_ref]
                axis = current.axis_index(update.append_dim)
                existing_length = int(current.values.shape[axis])
                self.app_projection.fields[field_ref] = current.append(
                    update.append_dim,
                    update.values,
                    update.coord_values,
                    max_length=update.max_length,
                    attrs_update=update.attrs_update,
                )
                append_duration_ms = round((time.monotonic() - append_started) * 1000.0, 3)
                field_append_apply_ms += append_duration_ms
                if append_duration_ms >= 5.0:
                    perf_log(
                        "frontend",
                        "field_append_apply_hiccup",
                        field_id=str(field_ref),
                        append_dim=update.append_dim,
                        existing_length=existing_length,
                        append_sample_count=int(len(update.coord_values)),
                        max_length=update.max_length,
                        values_shape=getattr(update.values, "shape", None),
                        duration_ms=append_duration_ms,
                    )
                if self.refresh_planner is not None:
                    pending_targets.update(self.refresh_planner.targets_for_field_replace(field_ref))
            pending_field_appends.clear()

        update_loop_started = time.monotonic()
        for message in messages:
            update = message.payload
            fragment_id = _message_fragment_id(message)
            if isinstance(update, FieldAppend):
                if self.app_spec is None:
                    continue
                field_ref = app_ref(update.field_id, fragment_id=fragment_id)
                update = self._trim_field_append(update, fragment_id=fragment_id)
                pending = pending_field_appends.get(field_ref)
                if pending is None:
                    pending_field_appends[field_ref] = update
                    continue
                if pending.append_dim != update.append_dim or pending.max_length != update.max_length:
                    flush_pending_field_appends()
                    pending_field_appends[field_ref] = update
                    continue
                axis = self.app_projection.fields[field_ref].axis_index(update.append_dim)
                pending_field_appends[field_ref] = self._trim_field_append(FieldAppend(
                    field_id=update.field_id,
                    append_dim=update.append_dim,
                    values=np.concatenate([pending.values, update.values], axis=axis),
                    coord_values=np.concatenate([pending.coord_values, update.coord_values], axis=0),
                    max_length=update.max_length,
                    attrs_update={**pending.attrs_update, **update.attrs_update},
                ), fragment_id=fragment_id)
                continue

            flush_pending_field_appends()
            if isinstance(update, FieldReplace):
                if self.app_spec is None:
                    continue
                field_ref = app_ref(update.field_id, fragment_id=fragment_id)
                replace_started = time.monotonic()
                field_replace_count += 1
                current = self.app_projection.fields[field_ref]
                coords_changed = update.coords is not None and not _coords_are_equal(current.coords, update.coords)
                coords = current.coords if update.coords is None or not coords_changed else update.coords
                self.app_projection.fields[field_ref] = current.with_values(update.values, coords=coords, attrs_update=update.attrs_update)
                replace_duration_ms = round((time.monotonic() - replace_started) * 1000.0, 3)
                field_replace_apply_ms += replace_duration_ms
                if replace_duration_ms >= 5.0:
                    perf_log(
                        "frontend",
                        "field_replace_apply_hiccup",
                        field_id=str(field_ref),
                        coords_changed=coords_changed,
                        values_shape=getattr(update.values, "shape", None),
                        duration_ms=replace_duration_ms,
                    )
                if self.refresh_planner is not None:
                    pending_targets.update(self.refresh_planner.targets_for_field_replace(field_ref, coords_changed=coords_changed))
            elif isinstance(update, ViewPatch):
                if self.app_projection is None:
                    continue
                view_ref = app_ref(update.view_id, fragment_id=fragment_id)
                self.app_projection.replace_view(view_ref, update.updates)
                if self.refresh_planner is not None:
                    pending_targets.update(self.refresh_planner.targets_for_view_patch(view_ref, set(update.updates.keys())))
            elif isinstance(update, OperatorPatch):
                if self.app_projection is None:
                    continue
                operator_ref = app_ref(update.operator_id, fragment_id=fragment_id)
                self.app_projection.replace_operator(operator_ref, update.updates)
                if self.refresh_planner is not None:
                    pending_targets.update(self.refresh_planner.targets_for_operator_patch(operator_ref, set(update.updates.keys())))
            elif isinstance(update, ControlPatch):
                if self.app_projection is None:
                    continue
                control_ref = app_ref(update.control_id, fragment_id=fragment_id)
                self.app_projection.replace_control(control_ref, update.updates)
                pending_targets.add(RefreshTarget.CONTROLS)
            elif isinstance(update, AppMetadataPatch):
                if self.app_spec is None:
                    continue
                self.app_projection.metadata.update(update.updates)
            elif isinstance(update, PanelPatch):
                if self.app_projection is None:
                    continue
                changes: dict[str, Any] = {}
                if update.control_ids is not None:
                    changes["control_ids"] = tuple(app_ref(item, fragment_id=fragment_id) for item in update.control_ids)
                if update.action_ids is not None:
                    changes["action_ids"] = tuple(app_ref(item, fragment_id=fragment_id) for item in update.action_ids)
                if update.view_ids is not None:
                    changes["view_ids"] = tuple(app_ref(item, fragment_id=fragment_id) for item in update.view_ids)
                if update.title is not None:
                    changes["title"] = update.title
                panel_id = update.panel_id if fragment_id == DEFAULT_FRAGMENT_ID else f"{fragment_id}:{update.panel_id}"
                if changes and self.app_projection.patch_panel(panel_id, **changes):
                    pending_targets.add(RefreshTarget.CONTROLS)
            elif isinstance(update, LayoutReplace):
                if self.app_projection is None:
                    continue
                self.app_projection.replace_active_layout_panels(update.panels, update.panel_grid)
                self._rebuild_panels()
                self._update_panel_visibility()
                if self.refresh_planner is not None:
                    pending_targets.update(self.refresh_planner.full_refresh_targets())
            elif isinstance(update, ValueChange):
                if self.refresh_planner is None:
                    continue
                control_value_keys = set()
                if self.app_spec is not None:
                    control_value_keys = {
                        _scoped_value_key(control, control_ref.fragment_id)
                        for control_ref, control in self.app_spec.iter_controls()
                    }
                for key, value in update.updates.items():
                    scoped_key = app_ref(key, fragment_id=fragment_id)
                    self._apply_frontend_value(scoped_key, value)
                    pending_targets.update(self.refresh_planner.targets_for_value_change(scoped_key))
                    if scoped_key in control_value_keys:
                        pending_targets.add(RefreshTarget.CONTROLS)
            elif isinstance(update, Status):
                if update.message:
                    if update.timeout_ms is not None:
                        self.statusBar().showMessage(update.message, update.timeout_ms)
                    else:
                        pending_status = update.message
                else:
                    self.statusBar().clearMessage()
            elif isinstance(update, (AppSpecDeclared, RoutedMessage)):
                continue
            else:
                msg = getattr(update, "message", str(update))
                pending_status = msg
                sys.stderr.write(f"{msg.rstrip()}\n")
                sys.stderr.flush()
        flush_pending_field_appends()
        update_loop_ms = round((time.monotonic() - update_loop_started) * 1000.0, 3)
        has_line_plot_targets = any(target.kind == "line_plot" for target in pending_targets)
        has_view_3d_targets = any(target.kind in VIEW_3D_TARGET_KINDS for target in pending_targets)
        has_state_graph_targets = any(target.kind == "state_graph" for target in pending_targets)
        if pending_targets:
            refresh_started = time.monotonic()
            self._apply_refresh_targets(pending_targets, refresh_deadline_s=refresh_deadline_s)
            refresh_apply_ms += round((time.monotonic() - refresh_started) * 1000.0, 3)
        if self._dirty_line_plot_views and not has_line_plot_targets:
            refresh_started = time.monotonic()
            self._flush_due_line_plot_refreshes(refresh_deadline_s=refresh_deadline_s)
            refresh_apply_ms += round((time.monotonic() - refresh_started) * 1000.0, 3)
        if (
            self._dirty_view_3d_targets
            and not has_view_3d_targets
            and (refresh_deadline_s is None or time.monotonic() < refresh_deadline_s)
        ):
            refresh_started = time.monotonic()
            self._flush_due_view_3d_refreshes(refresh_deadline_s=refresh_deadline_s)
            refresh_apply_ms += round((time.monotonic() - refresh_started) * 1000.0, 3)
        if (
            self._dirty_state_graph_views
            and not has_state_graph_targets
            and (refresh_deadline_s is None or time.monotonic() < refresh_deadline_s)
        ):
            refresh_started = time.monotonic()
            self._flush_due_state_graph_refreshes(refresh_deadline_s=refresh_deadline_s)
            refresh_apply_ms += round((time.monotonic() - refresh_started) * 1000.0, 3)
        if pending_status is not None:
            self.statusBar().showMessage(pending_status)
        local_duration_ms = round((time.monotonic() - handle_started) * 1000.0, 3)
        duration_ms = round((time.monotonic() - poll_started) * 1000.0, 3)
        should_log_handle = (
            local_duration_ms >= HANDLE_MESSAGES_LOG_THRESHOLD_MS
            or update_loop_ms >= HANDLE_MESSAGES_LOG_THRESHOLD_MS
            or refresh_apply_ms >= HANDLE_MESSAGES_LOG_THRESHOLD_MS
            or field_append_apply_ms >= HANDLE_MESSAGES_LOG_THRESHOLD_MS
            or field_replace_apply_ms >= HANDLE_MESSAGES_LOG_THRESHOLD_MS
            or len(updates) > 8
            or pending_status is not None
            or any(isinstance(update, AppSpecDeclared) for update in updates)
        )
        if should_log_handle:
            perf_log(
                "frontend",
                "handle_messages",
                update_count=len(updates),
                update_types=_update_type_counts(updates),
                coalesced_field_append_count=flushed_field_appends,
                appended_samples_by_field=appended_samples_by_field,
                field_append_apply_ms=round(field_append_apply_ms, 3),
                field_replace_count=field_replace_count,
                field_replace_apply_ms=round(field_replace_apply_ms, 3),
                update_loop_ms=update_loop_ms,
                refresh_apply_ms=round(refresh_apply_ms, 3),
                pending_target_count=len(pending_targets),
                pending_target_kinds=_target_kind_counts(pending_targets),
                dirty_line_plot_count=len(self._dirty_line_plot_views),
                dirty_view_3d_count=len(self._dirty_view_3d_targets),
                dirty_state_graph_count=len(self._dirty_state_graph_views),
                timer_gap_ms=timer_gap_ms,
                local_duration_ms=local_duration_ms,
                duration_ms=duration_ms,
            )

    def _on_entity_selected(self, entity_id: str) -> None:
        perf_log("frontend", "entity_selected", entity_id=entity_id)
        self._apply_frontend_value("selected_entity_id", entity_id)
        fragment_id: str | None = None
        if self.app_spec is not None:
            for geometry_ref, geometry in self.app_spec.iter_geometry_specs():
                if isinstance(geometry, MorphologyGeometrySpec) and entity_id in geometry.entity_ids:
                    fragment_id = geometry_ref.fragment_id
                    self._apply_frontend_value("selected_entity_label", geometry.label_for(entity_id))
                    break
            consumed = self._invoke_interaction_entity_click(entity_id)
            if not consumed and self._active_selection_action_id is not None:
                action_ref = app_ref(self._active_selection_action_id)
                action = self.app_spec.action(action_ref)
                if action is not None:
                    action = replace(action, id=action_ref)
                    payload = {
                        key: resolve_value(value, self.value_snapshot(), action_ref.fragment_id)
                        for key, value in action.payload.items()
                    }
                    payload[action.selection_payload_key] = entity_id
                    self._send_action(action, payload)
            elif not consumed:
                tags = {"fragment_id": fragment_id} if fragment_id is not None else None
                self._emit_command(EntityClicked(entity_id), tags=tags)
        if self.refresh_planner is not None:
            self._apply_refresh_targets(self.refresh_planner.targets_for_value_change("selected_entity_id"))

    def _on_control_changed(self, control, value) -> None:
        value_key = control.resolved_value_key()
        self._apply_frontend_value(value_key, value)
        control_ref = app_ref(control.id)
        perf_log(
            "frontend",
            "control_changed",
            control_id=str(control_ref),
            value_key=str(value_key),
            value=value,
            send_to_backend=control.send_to_backend,
        )
        if control.send_to_backend:
            local_value_key, tags = _command_ref(value_key)
            self._emit_command(ValueChange({local_value_key: value}), tags=tags)
        if self.refresh_planner is not None:
            self._apply_refresh_targets(
                self.refresh_planner.targets_for_value_change(value_key),
            )

    def _on_action_invoked(self, action, payload: dict[str, Any]) -> None:
        action_ref = app_ref(action.id)
        if self._invoke_interaction_action(action_ref.id, payload):
            return
        if action.selection_mode:
            self._toggle_selection_action_mode(action)
            return
        self._send_action(action, payload)

    def _send_action(self, action, payload: dict[str, Any]) -> None:
        action_ref = app_ref(action.id)
        if action_ref.id == "reset":
            self._emit_command(Reset(), tags={"fragment_id": action_ref.fragment_id})
        else:
            self._emit_command(InvokeAction(action_ref.id, payload), tags={"fragment_id": action_ref.fragment_id})

    def keyPressEvent(self, event) -> None:
        key_text = self._event_key_text(event)
        if key_text and self._invoke_interaction_key_press(key_text):
            event.accept()
            return
        if self.app_spec is not None:
            matched_action = self._action_for_event(event)
            if matched_action is not None:
                action_ref = app_ref(matched_action.id)
                payload = {
                    key: resolve_value(value, self.value_snapshot(), action_ref.fragment_id)
                    for key, value in matched_action.payload.items()
                }
                self._on_action_invoked(matched_action, payload)
                event.accept()
                return
        if event.key() == Qt.Key.Key_Space:
            self._emit_command(Reset())
            event.accept()
            return
        if key_text:
            self._emit_command(KeyPressed(key_text))
            event.accept()
            return
        super().keyPressEvent(event)

    def _action_for_event(self, event: QtGui.QKeyEvent):
        if self.app_spec is None:
            return None
        pressed = self._event_key_text(event)
        for action_ref, action in self.app_spec.iter_actions():
            for shortcut in action.shortcuts:
                normalized = QtGui.QKeySequence(shortcut).toString(QtGui.QKeySequence.SequenceFormat.PortableText)
                if normalized and normalized == pressed:
                    return replace(action, id=action_ref)
        return None

    def _toggle_selection_action_mode(self, action) -> None:
        if self._active_selection_action_id == action.id:
            self._active_selection_action_id = None
            self.statusBar().showMessage(f"{action.label} mode OFF")
            return
        self._active_selection_action_id = action.id
        self.statusBar().showMessage(f"{action.label} mode ON: click a segment to apply")

    def _event_key_text(self, event: QtGui.QKeyEvent) -> str:
        return QtGui.QKeySequence(event.modifiers().value | event.key()).toString(
            QtGui.QKeySequence.SequenceFormat.PortableText
        )

    def _interaction_context(self) -> "FrontendInteractionContext":
        return FrontendInteractionContext(self)

    def _invoke_interaction_action(self, action_id: str | AppRef, payload: dict[str, Any]) -> bool:
        target = self.interaction_target
        if target is None:
            return False
        handler = getattr(target, "on_action", None)
        if handler is None:
            return False
        return bool(handler(str(action_id), payload, self._interaction_context()))

    def _invoke_interaction_key_press(self, key: str) -> bool:
        target = self.interaction_target
        if target is None:
            return False
        handler = getattr(target, "on_key_press", None)
        if handler is None:
            return False
        return bool(handler(key, self._interaction_context()))

    def _invoke_interaction_entity_click(self, entity_id: str) -> bool:
        target = self.interaction_target
        if target is None:
            return False
        handler = getattr(target, "on_entity_clicked", None)
        if handler is None:
            return False
        return bool(handler(entity_id, self._interaction_context()))

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)
