from __future__ import annotations

import time
from typing import Any

from PyQt6 import QtGui, QtWidgets
from PyQt6.QtCore import Qt

from compneurovis.core.runtime.performance import perf_log
from compneurovis.core import (
    AppRef,
    app_ref,
    AppSpec,
    Field,
    DEFAULT_FRAGMENT_ID,
)
from compneurovis.core.projection import AppProjection
from compneurovis.core.selections import selection_after_click
from compneurovis.frontends.base import FrontendBase
from compneurovis.core.messages import (
    command_message,
    EntityClicked,
    InvokeAction,
    KeyPressed,
    Message,
    MessagePayload,
    ValueChange,
)
from compneurovis.frontends.vispy.interaction_context import FrontendInteractionContext
from compneurovis.frontends.vispy.interaction_target import (
    resolve_interaction_target_source,
)
from compneurovis.frontends.vispy.registries.operators import (
    OperatorResolveContext,
    operator_adapter,
)
from compneurovis.frontends.vispy.registries.controls import (
    ResolvedAction,
    ResolvedControl,
)
from compneurovis.frontends.vispy.plugins import load_vispy_plugins
from compneurovis.frontends.vispy.panel_manager import PanelManager
from compneurovis.frontends.vispy.update_processor import (
    AppUpdateProcessor,
    _scoped_value_key,
)
from compneurovis.frontends.vispy.refresh_planning import (
    RefreshPlanner,
    RefreshTarget,
)
from compneurovis.frontends.vispy.bindings import resolve_binding
HANDLE_MESSAGES_LOG_THRESHOLD_MS = 5.0
# Which target kinds route to which visual, their refresh order, and the full set
# are DERIVED from the 3-D visual registry (each visual declares its own targets).
# The frontend enumerates no per-widget kinds.

def _command_ref(value: str | AppRef) -> tuple[str, dict[str, Any]]:
    ref = app_ref(value)
    return ref.id, {"fragment_id": ref.fragment_id}


class VispyFrontendWindow(QtWidgets.QMainWindow, FrontendBase):
    def __init__(
        self,
        *,
        title: str | None = None,
        interaction_target: Any = None,
        mount_panels: bool = True,
    ):
        super().__init__()
        FrontendBase.__init__(self)
        self._title = title
        self._mount_panels = bool(mount_panels)
        self.app_projection: AppProjection | None = None
        self.refresh_planner: RefreshPlanner | None = None
        self._active_selection_action_ref: AppRef | None = None
        self._active_selection_ref: AppRef | None = None
        if interaction_target is not None:
            self.interaction_target = resolve_interaction_target_source(
                interaction_target
            )
        else:
            self.interaction_target = None

        self._last_poll_started_s: float | None = None
        self._plugin_preload_error: Exception | None = None
        self._plugins_preloaded = False

        self._loading_label = QtWidgets.QLabel("Loading visualization...")
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._stack = QtWidgets.QStackedWidget(self)
        self._stack.addWidget(self._loading_label)
        self.panel_manager = PanelManager(self, self._stack)
        self.update_processor = AppUpdateProcessor(self)
        self._panel_hosts = self.panel_manager.panel_hosts

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

    def preload_plugins(self) -> None:
        """Load frontend capabilities while backend startup is still running."""
        if not self._mount_panels:
            return
        if self._plugins_preloaded or self._plugin_preload_error is not None:
            return
        try:
            load_vispy_plugins()
        except Exception as exc:
            self._plugin_preload_error = exc
            return
        self._plugins_preloaded = True

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

    def inspection_surface(self, panel_id: str, name: str) -> Any | None:
        """Return one explicitly addressed host inspection surface, if exposed."""
        if not self._mount_panels:
            return None
        return self.panel_manager.inspection_surface(panel_id, name)

    def _show_loading_state(self, message: str = "Loading visualization...") -> None:
        self._loading_label.setText(message)
        self._stack.setCurrentWidget(self._loading_label)

    def _show_content_state(self) -> None:
        if not self._mount_panels:
            return
        if self.panel_manager.layout_splitter is not None:
            self._stack.setCurrentWidget(self.panel_manager.layout_splitter)

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
            lambda actor, value, _value_key=value_key: actor._set_frontend_value(
                _value_key, value
            ),
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
        return (
            self.app_projection.active_layout()
            if self.app_projection is not None
            else None
        )

    def _set_app_spec(self, app_spec: AppSpec) -> None:
        started = time.monotonic()
        if self._plugin_preload_error is not None:
            raise RuntimeError(
                "Vispy plugin preload failed"
            ) from self._plugin_preload_error
        if self._mount_panels:
            load_vispy_plugins()
        self.app_projection = AppProjection(app_spec)
        app_spec = self.app_projection.spec
        self.refresh_planner = RefreshPlanner(
            lambda: self.app_projection.spec,
            self.app_projection.active_layout,
        )
        self._active_selection_action_ref = None
        self._active_selection_ref = None
        self.setWindowTitle(self._title or self._active_layout().title)
        for control_ref, control in app_spec.iter_controls():
            value_key = _scoped_value_key(control, control_ref.fragment_id)
            initial_value = self.values.get(value_key, control.default_value())
            self._bind_frontend_value(value_key, initial_value)
        for selection_ref, selection in app_spec.iter_selections():
            initial = self.values.get(selection_ref, list(selection.initial))
            self._bind_frontend_value(selection_ref, initial)

        rebuild_ms = 0.0
        full_refresh_ms = 0.0
        if self._mount_panels:
            rebuild_started = time.monotonic()
            self._rebuild_panels()
            rebuild_ms = round((time.monotonic() - rebuild_started) * 1000.0, 3)

            refresh_started = time.monotonic()
            self._update_panel_visibility()
            self._apply_refresh_targets(
                self.refresh_planner.full_refresh_targets(),
                force_scene=True,
                force_views=True,
            )
            full_refresh_ms = round(
                (time.monotonic() - refresh_started) * 1000.0, 3
            )
            self._show_content_state()
        perf_log(
            "frontend",
            "set_app_spec",
            view_count=sum(1 for _ in app_spec.iter_view_specs()),
            field_count=sum(1 for _ in app_spec.iter_field_specs()),
            geometry_count=sum(1 for _ in app_spec.iter_geometry_specs()),
            panel_count=len(self._active_layout().panels),
            panels_mounted=self._mount_panels,
            rebuild_panels_ms=rebuild_ms,
            full_refresh_ms=full_refresh_ms,
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )

    def _rebuild_panels(self) -> None:
        if not self._mount_panels:
            return
        self.panel_manager.rebuild()

    def _resolved_panel_grid(self) -> tuple[tuple[str, ...], ...]:
        if self.app_spec is None:
            return ()
        return self._active_layout().panel_grid

    def _make_panel_for_cell(self, cell_id: str) -> QtWidgets.QWidget | None:
        if not self._mount_panels:
            return None
        return self.panel_manager.make_panel(cell_id)

    def _remount_panel(self, panel_id: str) -> bool:
        if not self._mount_panels:
            return True
        return self.panel_manager.remount(panel_id)

    def _resolved_controls_and_actions(
        self, panel_id: str
    ) -> tuple[list[ResolvedControl], list[ResolvedAction]]:
        if self.app_spec is None:
            return [], []
        panel = self._active_layout().panel(panel_id)
        if panel is None:
            return [], []
        controls: list[ResolvedControl] = []
        for control_id in panel.control_ids:
            control_ref = app_ref(control_id)
            control = self.app_spec.control(control_ref)
            if control is not None:
                controls.append(
                    ResolvedControl(
                        ref=control_ref,
                        value_ref=_scoped_value_key(
                            control, control_ref.fragment_id
                        ),
                        spec=control,
                    )
                )
        actions: list[ResolvedAction] = []
        for action_id in panel.action_ids:
            action_ref = app_ref(action_id)
            action = self.app_spec.action(action_ref)
            if action is not None:
                actions.append(ResolvedAction(ref=action_ref, spec=action))
        return controls, actions

    def _update_panel_visibility(self) -> None:
        if not self._mount_panels:
            return
        self.panel_manager.update_visibility()

    def _apply_panel_sizes(self) -> None:
        if not self._mount_panels:
            return
        self.panel_manager.apply_sizes()

    def _resolve_view_input(
        self,
        input_id: str | AppRef,
        fragment_id: str,
        values: dict,
        *,
        _operator_path: tuple[AppRef, ...] = (),
    ):
        """Resolve one view input to a Field.

        A stored field id resolves directly; an operator id resolves to that
        operator's computed output field via the operator's registered adapter
        (e.g. a grid slice). The frontend holds no operator-kind knowledge -- from
        the consuming view's point of view an operator is just another data source.
        """
        input_ref = app_ref(input_id, fragment_id=fragment_id)
        operator = self.app_spec.operator(input_ref)
        resolver = getattr(operator_adapter(operator), "resolve_field", None)
        if resolver is not None:
            if input_ref in _operator_path:
                cycle = (*_operator_path, input_ref)
                rendered = " -> ".join(str(ref) for ref in cycle)
                raise ValueError(f"Operator dependency cycle: {rendered}")
            operator_path = (*_operator_path, input_ref)
            return resolver(
                operator,
                OperatorResolveContext(
                    get_field=lambda field_id: self._resolve_view_input(
                        field_id,
                        fragment_id=input_ref.fragment_id,
                        values=values,
                        _operator_path=operator_path,
                    ),
                    get_geometry=lambda geometry_id: self.app_spec.geometry(
                        app_ref(
                            geometry_id,
                            fragment_id=input_ref.fragment_id,
                        )
                    ),
                    values=values,
                    fragment_id=input_ref.fragment_id,
                ),
            )
        return self._field(input_ref, fragment_id=input_ref.fragment_id)

    def _apply_refresh_targets(
        self,
        targets: set[RefreshTarget],
        *,
        force_scene: bool = False,
        force_views: bool = False,
        refresh_deadline_s: float | None = None,
    ) -> None:
        if not self._mount_panels:
            return
        self.panel_manager.apply_refresh_targets(
            targets,
            force=force_scene or force_views,
            refresh_deadline_s=refresh_deadline_s,
        )

    def _flush_panel_host_refreshes(
        self,
        *,
        force: bool = False,
        now: float | None = None,
        refresh_deadline_s: float | None = None,
    ) -> int:
        if not self._mount_panels:
            return 0
        return self.panel_manager.flush(
            force=force, now=now, refresh_deadline_s=refresh_deadline_s
        )

    def _has_pending_panel_refreshes(self) -> bool:
        if not self._mount_panels:
            return False
        return self.panel_manager.has_pending_refreshes()

    def flush_due_refreshes(
        self, *, now: float, refresh_deadline_s: float | None = None
    ) -> None:
        if not self._mount_panels:
            return
        self.panel_manager.flush_due(
            now=now, refresh_deadline_s=refresh_deadline_s
        )

    def handle(self, message: Message[MessagePayload]) -> None:
        self._handle_update_messages(
            [message], poll_started=time.monotonic(), timer_gap_ms=None
        )

    def compact_update_messages(
        self, messages: list[Message[MessagePayload]]
    ) -> list[Message[MessagePayload]]:
        return self.update_processor.compact_update_messages(messages)

    def _emit_command(
        self, command: MessagePayload, *, tags: dict[str, Any] | None = None
    ) -> None:
        self.emit(command_message(command, tags=tags))

    def _handle_update_messages(
        self,
        messages: list[Message[MessagePayload]],
        *,
        poll_started: float,
        timer_gap_ms: float | None,
        refresh_deadline_s: float | None = None,
    ) -> None:
        self.update_processor.handle_update_messages(
            messages,
            poll_started=poll_started,
            timer_gap_ms=timer_gap_ms,
            refresh_deadline_s=refresh_deadline_s,
        )

    def _on_entity_selected(
        self,
        view_id: str | AppRef,
        selection_role: str,
        entity_id: str,
    ) -> None:
        if self.app_spec is None:
            return
        view_ref = app_ref(view_id)
        authored_view = self.app_spec.view(view_ref)
        selections = getattr(authored_view, "selections", {})
        selection_id = selections.get(selection_role)
        if selection_id is None:
            raise ValueError(
                f"Selectable view {view_ref!s} has no selection role "
                f"{selection_role!r}"
            )
        selection_ref = app_ref(selection_id, fragment_id=view_ref.fragment_id)
        selection = self.app_spec.selection(selection_ref)
        if selection is None:
            raise ValueError(
                f"View {view_ref!s} references unknown selection {selection_ref!s}"
            )
        self._active_selection_ref = selection_ref
        entity_id = str(entity_id)
        selected = selection_after_click(
            self.values.get(selection_ref, selection.initial),
            entity_id,
            multiple=selection.multiple,
        )
        perf_log(
            "frontend",
            "entity_selected",
            view_id=str(view_ref),
            selection_id=str(selection_ref),
            entity_id=entity_id,
        )
        self._apply_frontend_value(selection_ref, selected)
        consumed = self._invoke_interaction_entity_click(entity_id)
        if not consumed and self._active_selection_action_ref is not None:
            action_ref = self._active_selection_action_ref
            action = self.app_spec.action(action_ref)
            if action is not None:
                payload = {
                    key: resolve_binding(
                        value,
                        self.value_snapshot(),
                        action_ref.fragment_id,
                    )
                    for key, value in action.payload.items()
                }
                payload[action.selection_payload_key] = entity_id
                self._send_action(
                    ResolvedAction(ref=action_ref, spec=action), payload
                )
        elif not consumed:
            self._emit_command(
                EntityClicked(selection_ref.id, entity_id),
                tags={"fragment_id": selection_ref.fragment_id},
            )
        if self.refresh_planner is not None:
            self._apply_refresh_targets(
                self.refresh_planner.targets_for_value_change(selection_ref),
                force_scene=True,
            )

    def _on_control_changed(self, control: ResolvedControl, value: Any) -> None:
        value_key = control.value_ref
        self._apply_frontend_value(value_key, value)
        perf_log(
            "frontend",
            "control_changed",
            control_id=str(control.ref),
            value_key=str(value_key),
            value=value,
            send_to_backend=control.spec.send_to_backend,
        )
        if control.spec.send_to_backend:
            local_value_key, tags = _command_ref(value_key)
            self._emit_command(ValueChange({local_value_key: value}), tags=tags)
        if self.refresh_planner is not None:
            self._apply_refresh_targets(
                self.refresh_planner.targets_for_value_change(value_key),
            )

    def _on_action_invoked(
        self, action: ResolvedAction, payload: dict[str, Any]
    ) -> None:
        if self._invoke_interaction_action(action.ref, payload):
            return
        if action.spec.selection_mode:
            self._toggle_selection_action_mode(action)
            return
        self._send_action(action, payload)

    def _send_action(
        self, action: ResolvedAction, payload: dict[str, Any]
    ) -> None:
        self._emit_command(
            InvokeAction(action.ref.id, payload),
            tags={"fragment_id": action.ref.fragment_id},
        )

    def keyPressEvent(self, event) -> None:
        key_text = self._event_key_text(event)
        if key_text and self._invoke_interaction_key_press(key_text):
            event.accept()
            return
        if self.app_spec is not None:
            matched_actions = self._actions_for_event(event)
            for matched_action in matched_actions:
                payload = {
                    key: resolve_binding(
                        value,
                        self.value_snapshot(),
                        matched_action.ref.fragment_id,
                    )
                    for key, value in matched_action.spec.payload.items()
                }
                self._on_action_invoked(matched_action, payload)
            if matched_actions:
                event.accept()
                return
        if key_text:
            self._emit_command(KeyPressed(key_text))
            event.accept()
            return
        super().keyPressEvent(event)

    def _actions_for_event(
        self, event: QtGui.QKeyEvent
    ) -> tuple[ResolvedAction, ...]:
        if self.app_spec is None:
            return ()
        pressed = self._event_key_text(event)
        matches: list[ResolvedAction] = []
        for action_ref, action in self.app_spec.iter_actions():
            for shortcut in action.shortcuts:
                normalized = QtGui.QKeySequence(shortcut).toString(
                    QtGui.QKeySequence.SequenceFormat.PortableText
                )
                if normalized and normalized == pressed:
                    matches.append(ResolvedAction(ref=action_ref, spec=action))
                    break
        return tuple(matches)

    def _toggle_selection_action_mode(self, action: ResolvedAction) -> None:
        if self._active_selection_action_ref == action.ref:
            self._active_selection_action_ref = None
            self.statusBar().showMessage(f"{action.spec.label} mode OFF")
            return
        self._active_selection_action_ref = action.ref
        self.statusBar().showMessage(
            f"{action.spec.label} mode ON: click a segment to apply"
        )

    def _event_key_text(self, event: QtGui.QKeyEvent) -> str:
        return QtGui.QKeySequence(event.modifiers().value | event.key()).toString(
            QtGui.QKeySequence.SequenceFormat.PortableText
        )

    def _interaction_context(self) -> "FrontendInteractionContext":
        return FrontendInteractionContext(self)

    def _invoke_interaction_action(
        self, action_id: str | AppRef, payload: dict[str, Any]
    ) -> bool:
        target = self.interaction_target
        if target is None:
            return False
        handler = getattr(target, "on_action", None)
        if handler is None:
            return False
        return bool(handler(app_ref(action_id), payload, self._interaction_context()))

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
