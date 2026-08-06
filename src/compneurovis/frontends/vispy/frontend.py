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
from compneurovis.core import (
    ActionSpec,
    AppRef,
    app_ref,
    AppSpec,
    ControlSpec,
    Field,
    DEFAULT_FRAGMENT_ID,
)
from compneurovis.frontends.vispy.builtin_panel_hosts import register_builtin_panel_hosts
from compneurovis.core.projection import AppProjection
from compneurovis.core.selections import selection_after_click
from compneurovis.frontends.base import FrontendBase
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
from compneurovis.frontends.vispy.interaction_target import (
    resolve_interaction_target_source,
)
from compneurovis.frontends.vispy.operator_adapters import (
    OperatorResolveContext,
    operator_adapter,
)
from compneurovis.frontends.vispy.panel_hosts import (
    PanelHostContext,
    PanelHostLifecycle,
    panel_host_factory,
)
from compneurovis.frontends.vispy.plugins import load_vispy_plugins
from compneurovis.frontends.vispy.refresh_planning import (
    RefreshPlanner,
    RefreshTarget,
    _target_kind_counts,
)
from compneurovis.frontends.vispy.view_inputs.bindings import resolve_binding
HANDLE_MESSAGES_LOG_THRESHOLD_MS = 5.0
# Which target kinds route to which visual, their refresh order, and the full set
# are DERIVED from the 3-D visual registry (each visual declares its own targets).
# The frontend enumerates no per-widget kinds.


def _coords_are_equal(
    left: dict[str, np.ndarray], right: dict[str, np.ndarray]
) -> bool:
    if left.keys() != right.keys():
        return False
    return all(
        np.array_equal(np.asarray(left[key]), np.asarray(right[key])) for key in left
    )


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
    return Message(
        type=message.type, intent=message.intent, payload=payload, tags=message.tags
    )


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
        self._active_selection_ref: AppRef | None = None
        if interaction_target is not None:
            self.interaction_target = resolve_interaction_target_source(
                interaction_target
            )
        else:
            self.interaction_target = None

        self.viewports: dict[str | AppRef, Any] = {}
        self._view_to_panel_id: dict[str, str] = {}
        self._last_poll_started_s: float | None = None
        self.controls_panels: dict[str, Any] = {}
        self._panel_hosts: dict[str, PanelHostLifecycle] = {}

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
    def viewport(self) -> Any | None:
        return next(iter(self.viewports.values()), None)

    def controls_panel(self, panel_id: str) -> Any | None:
        return self.controls_panels.get(panel_id)

    def viewport_for(self, view_id: str | AppRef) -> Any | None:
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
        register_builtin_panel_hosts()
        load_vispy_plugins()
        self.app_projection = AppProjection(app_spec)
        app_spec = self.app_projection.spec
        self.refresh_planner = RefreshPlanner(
            app_spec, self.app_projection.active_layout
        )
        self._active_selection_action_id = None
        self._active_selection_ref = None
        self.setWindowTitle(self._title or self._active_layout().title)
        for control_ref, control in app_spec.iter_controls():
            value_key = _scoped_value_key(control, control_ref.fragment_id)
            initial_value = self.values.get(value_key, control.default_value())
            self._bind_frontend_value(value_key, initial_value)
        for selection_ref, selection in app_spec.iter_selections():
            initial = self.values.get(selection_ref, list(selection.initial))
            self._bind_frontend_value(selection_ref, initial)

        rebuild_started = time.monotonic()
        self._rebuild_panels()
        rebuild_ms = round((time.monotonic() - rebuild_started) * 1000.0, 3)

        refresh_started = time.monotonic()
        self._update_panel_visibility()
        self._apply_refresh_targets(
            self.refresh_planner.full_refresh_targets(),
            force_scene=True,
            force_extensions=True,
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

    def _rebuild_panels(self) -> None:
        started = time.monotonic()
        for lifecycle in self._panel_hosts.values():
            lifecycle.dispose()
        self._panel_hosts.clear()
        self.viewports.clear()
        self._view_to_panel_id.clear()
        self.controls_panels.clear()

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
            panel_host_count=len(self._panel_hosts),
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
        context = PanelHostContext(
            app_spec=self.app_spec,
            active_layout=self._active_layout,
            value_snapshot=self.value_snapshot,
            values_for_fragment=self._values_for_fragment,
            field=self._field,
            fields=lambda: self.app_projection.fields,
            resolve_input=self._resolve_extension_input,
            controls_and_actions=self._resolved_controls_and_actions,
            control_changed=self._on_control_changed,
            action_invoked=self._on_action_invoked,
            entity_selected=self._on_entity_selected,
        )
        lifecycle = panel_host_factory(panel_spec.kind)(context, panel_spec)
        if not isinstance(lifecycle, PanelHostLifecycle):
            raise TypeError(
                f"Panel-host factory for {panel_spec.kind!r} must return a "
                "PanelHostLifecycle"
            )
        if not isinstance(lifecycle.widget, QtWidgets.QWidget):
            raise TypeError(
                f"Panel-host factory for {panel_spec.kind!r} must expose a QWidget"
            )
        self._panel_hosts[panel_spec.id] = lifecycle
        for view_id in panel_spec.view_ids:
            self._view_to_panel_id[view_id] = panel_spec.id

        self.viewports.update(lifecycle.viewports)
        if lifecycle.controls_surface is not None:
            self.controls_panels[panel_spec.id] = lifecycle.controls_surface

        perf_log(
            "frontend",
            "create_panel",
            panel_id=panel_spec.id,
            panel_kind=panel_spec.kind,
            view_ids=panel_spec.view_ids,
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )
        return lifecycle.widget

    def _resolved_controls_and_actions(
        self, panel_id: str
    ) -> tuple[list[ControlSpec], list[ActionSpec]]:
        if self.app_spec is None:
            return [], []
        panel = self._active_layout().panel(panel_id)
        if panel is None:
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
        for lifecycle in self._panel_hosts.values():
            lifecycle.update_visibility()
        self._apply_panel_sizes()

    def _apply_panel_sizes(self) -> None:
        if self._layout_splitter is None:
            return
        width = max(self.width(), 1)
        height = max(self.height(), 1)
        n_rows = self._layout_splitter.count()
        if n_rows == 0:
            return
        last_widget = self._layout_splitter.widget(n_rows - 1)
        last_is_compact = any(
            lifecycle.widget is last_widget and lifecycle.compact_when_last
            for lifecycle in self._panel_hosts.values()
        )
        if last_is_compact and n_rows > 1:
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

    def _resolve_extension_input(self, input_id: str, fragment_id: str, values: dict):
        """Resolve one extension-view input to a Field.

        A stored field id resolves directly; an operator id resolves to that
        operator's computed output field via the operator's registered adapter
        (e.g. a grid slice). The frontend holds no operator-kind knowledge -- from
        the consuming view's point of view an operator is just another data source.
        """
        operator = self.app_spec.operator(app_ref(input_id, fragment_id=fragment_id))
        resolver = getattr(operator_adapter(operator), "resolve_field", None)
        if resolver is not None:
            return resolver(
                operator,
                OperatorResolveContext(
                    get_field=lambda field_id: self._field(
                        field_id,
                        fragment_id=fragment_id,
                    ),
                    get_geometry=lambda geometry_id: self.app_spec.geometry(
                        app_ref(geometry_id, fragment_id=fragment_id)
                    ),
                    values=values,
                    fragment_id=fragment_id,
                ),
            )
        return self._field(input_id, fragment_id=fragment_id)

    def _apply_refresh_targets(
        self,
        targets: set[RefreshTarget],
        *,
        force_scene: bool = False,
        force_extensions: bool = False,
        refresh_deadline_s: float | None = None,
    ) -> None:
        if not targets:
            return
        started = time.monotonic()
        claimed_target_count = 0
        for target in sorted(
            targets, key=lambda item: (str(item.view_id or ""), item.kind)
        ):
            for lifecycle in self._panel_hosts.values():
                if lifecycle.accepts_refresh_target(target):
                    lifecycle.queue_refresh(target)
                    claimed_target_count += 1

        refreshed_count = 0
        if refresh_deadline_s is None or time.monotonic() < refresh_deadline_s:
            refreshed_count = self._flush_panel_host_refreshes(
                force=force_scene or force_extensions,
                now=started,
                refresh_deadline_s=refresh_deadline_s,
            )
        deferred_count = sum(
            int(lifecycle.has_pending_refresh)
            for lifecycle in self._panel_hosts.values()
        )
        perf_log(
            "frontend",
            "apply_refresh_targets",
            target_count=len(targets),
            target_kinds=_target_kind_counts(targets),
            claimed_target_count=claimed_target_count,
            refreshed_panel_count=refreshed_count,
            deferred_panel_count=deferred_count,
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )

    def _flush_panel_host_refreshes(
        self,
        *,
        force: bool = False,
        now: float | None = None,
        refresh_deadline_s: float | None = None,
    ) -> int:
        refreshed = 0
        for lifecycle in self._panel_hosts.values():
            if not lifecycle.has_pending_refresh:
                continue
            if refresh_deadline_s is not None and time.monotonic() >= refresh_deadline_s:
                break
            refreshed += lifecycle.flush_refreshes(
                force=force,
                now=now,
                refresh_deadline_s=refresh_deadline_s,
            )
        return refreshed

    def _has_pending_panel_refreshes(self) -> bool:
        return any(
            lifecycle.has_pending_refresh
            for lifecycle in self._panel_hosts.values()
        )

    def flush_due_refreshes(
        self, *, now: float, refresh_deadline_s: float | None = None
    ) -> None:
        if self._has_pending_panel_refreshes() and (
            refresh_deadline_s is None or time.monotonic() < refresh_deadline_s
        ):
            self._flush_panel_host_refreshes(
                now=now, refresh_deadline_s=refresh_deadline_s
            )

    def handle(self, message: Message[MessagePayload]) -> None:
        self._handle_update_messages(
            [message], poll_started=time.monotonic(), timer_gap_ms=None
        )

    def compact_update_messages(
        self, messages: list[Message[MessagePayload]]
    ) -> list[Message[MessagePayload]]:
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

        def ensure_field(
            field_ref: AppRef,
        ) -> dict[str, Message[MessagePayload] | None]:
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
                    attrs_update = {
                        **previous.payload.attrs_update,
                        **update.attrs_update,
                    }
                    coords = (
                        update.coords
                        if update.coords is not None
                        else previous.payload.coords
                    )
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
                    ensure_field(field_ref)["append"] = self._trim_field_append_message(
                        message
                    )
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
                update_types_before=_update_type_counts(
                    [message.payload for message in messages]
                ),
                update_types_after=_update_type_counts(
                    [message.payload for message in compacted]
                ),
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
        field_ref = app_ref(
            left.field_id, fragment_id=_message_fragment_id(left_message)
        )
        field = (
            self.app_projection.field(field_ref)
            if self.app_projection is not None
            else None
        )
        if field is None:
            return None
        try:
            axis = field.axis_index(left.append_dim)
            merged = FieldAppend(
                field_id=left.field_id,
                append_dim=left.append_dim,
                values=np.concatenate([left.values, right.values], axis=axis),
                coord_values=np.concatenate(
                    [left.coord_values, right.coord_values], axis=0
                ),
                max_length=right.max_length,
                attrs_update={**left.attrs_update, **right.attrs_update},
            )
        except Exception:
            return None
        return self._trim_field_append_message(
            _replace_message_payload(right_message, merged)
        )

    def _trim_field_append_message(
        self,
        message: Message[MessagePayload],
    ) -> Message[MessagePayload]:
        update = message.payload
        if not isinstance(update, FieldAppend):
            return message
        trimmed = self._trim_field_append(
            update, fragment_id=_message_fragment_id(message)
        )
        if trimmed is update:
            return message
        return _replace_message_payload(message, trimmed)

    def _trim_field_append(
        self, update: FieldAppend, *, fragment_id: str
    ) -> FieldAppend:
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
            coord_values=np.asarray(update.coord_values)[:0]
            if max_length == 0
            else np.asarray(update.coord_values)[-max_length:],
            max_length=update.max_length,
            attrs_update=update.attrs_update,
        )

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
                appended_samples_by_field[field_key] = appended_samples_by_field.get(
                    field_key, 0
                ) + int(len(update.coord_values))
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
                append_duration_ms = round(
                    (time.monotonic() - append_started) * 1000.0, 3
                )
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
                    pending_targets.update(
                        self.refresh_planner.targets_for_field_replace(field_ref)
                    )
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
                if (
                    pending.append_dim != update.append_dim
                    or pending.max_length != update.max_length
                ):
                    flush_pending_field_appends()
                    pending_field_appends[field_ref] = update
                    continue
                axis = self.app_projection.fields[field_ref].axis_index(
                    update.append_dim
                )
                pending_field_appends[field_ref] = self._trim_field_append(
                    FieldAppend(
                        field_id=update.field_id,
                        append_dim=update.append_dim,
                        values=np.concatenate(
                            [pending.values, update.values], axis=axis
                        ),
                        coord_values=np.concatenate(
                            [pending.coord_values, update.coord_values], axis=0
                        ),
                        max_length=update.max_length,
                        attrs_update={**pending.attrs_update, **update.attrs_update},
                    ),
                    fragment_id=fragment_id,
                )
                continue

            flush_pending_field_appends()
            if isinstance(update, FieldReplace):
                if self.app_spec is None:
                    continue
                field_ref = app_ref(update.field_id, fragment_id=fragment_id)
                replace_started = time.monotonic()
                field_replace_count += 1
                current = self.app_projection.fields[field_ref]
                coords_changed = update.coords is not None and not _coords_are_equal(
                    current.coords, update.coords
                )
                coords = (
                    current.coords
                    if update.coords is None or not coords_changed
                    else update.coords
                )
                self.app_projection.fields[field_ref] = current.with_values(
                    update.values, coords=coords, attrs_update=update.attrs_update
                )
                replace_duration_ms = round(
                    (time.monotonic() - replace_started) * 1000.0, 3
                )
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
                    pending_targets.update(
                        self.refresh_planner.targets_for_field_replace(
                            field_ref, coords_changed=coords_changed
                        )
                    )
            elif isinstance(update, ViewPatch):
                if self.app_projection is None:
                    continue
                view_ref = app_ref(update.view_id, fragment_id=fragment_id)
                self.app_projection.replace_view(view_ref, update.updates)
                if self.refresh_planner is not None:
                    pending_targets.update(
                        self.refresh_planner.targets_for_view_patch(
                            view_ref, set(update.updates.keys())
                        )
                    )
            elif isinstance(update, OperatorPatch):
                if self.app_projection is None:
                    continue
                operator_ref = app_ref(update.operator_id, fragment_id=fragment_id)
                self.app_projection.replace_operator(operator_ref, update.updates)
                if self.refresh_planner is not None:
                    pending_targets.update(
                        self.refresh_planner.targets_for_operator_patch(
                            operator_ref, set(update.updates.keys())
                        )
                    )
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
                    changes["control_ids"] = tuple(
                        app_ref(item, fragment_id=fragment_id)
                        for item in update.control_ids
                    )
                if update.action_ids is not None:
                    changes["action_ids"] = tuple(
                        app_ref(item, fragment_id=fragment_id)
                        for item in update.action_ids
                    )
                if update.view_ids is not None:
                    changes["view_ids"] = tuple(
                        app_ref(item, fragment_id=fragment_id)
                        for item in update.view_ids
                    )
                if update.title is not None:
                    changes["title"] = update.title
                panel_id = (
                    update.panel_id
                    if fragment_id == DEFAULT_FRAGMENT_ID
                    else f"{fragment_id}:{update.panel_id}"
                )
                if changes and self.app_projection.patch_panel(panel_id, **changes):
                    pending_targets.add(RefreshTarget.CONTROLS)
            elif isinstance(update, LayoutReplace):
                if self.app_projection is None:
                    continue
                self.app_projection.replace_active_layout_panels(
                    update.panels, update.panel_grid
                )
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
                    pending_targets.update(
                        self.refresh_planner.targets_for_value_change(scoped_key)
                    )
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
        if pending_targets:
            refresh_started = time.monotonic()
            self._apply_refresh_targets(
                pending_targets, refresh_deadline_s=refresh_deadline_s
            )
            refresh_apply_ms += round((time.monotonic() - refresh_started) * 1000.0, 3)
        if (
            self._has_pending_panel_refreshes()
            and (refresh_deadline_s is None or time.monotonic() < refresh_deadline_s)
        ):
            refresh_started = time.monotonic()
            self._flush_panel_host_refreshes(
                refresh_deadline_s=refresh_deadline_s
            )
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
                dirty_panel_count=sum(
                    int(lifecycle.has_pending_refresh)
                    for lifecycle in self._panel_hosts.values()
                ),
                timer_gap_ms=timer_gap_ms,
                local_duration_ms=local_duration_ms,
                duration_ms=duration_ms,
            )

    def _on_entity_selected(self, view_id: str | AppRef, entity_id: str) -> None:
        if self.app_spec is None:
            return
        view_ref = app_ref(view_id)
        authored_view = self.app_spec.view(view_ref)
        selection_ids = tuple(getattr(authored_view, "selections", {}).values())
        if len(selection_ids) != 1:
            raise ValueError(
                f"Selectable view {view_ref!s} must declare exactly one selection"
            )
        selection_ref = app_ref(selection_ids[0], fragment_id=view_ref.fragment_id)
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
        if not consumed and self._active_selection_action_id is not None:
            action_ref = app_ref(self._active_selection_action_id)
            action = self.app_spec.action(action_ref)
            if action is not None:
                action = replace(action, id=action_ref)
                payload = {
                    key: resolve_binding(
                        value,
                        self.value_snapshot(),
                        action_ref.fragment_id,
                    )
                    for key, value in action.payload.items()
                }
                payload[action.selection_payload_key] = entity_id
                self._send_action(action, payload)
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
            self._emit_command(
                InvokeAction(action_ref.id, payload),
                tags={"fragment_id": action_ref.fragment_id},
            )

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
                    key: resolve_binding(
                        value, self.value_snapshot(), action_ref.fragment_id
                    )
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
                normalized = QtGui.QKeySequence(shortcut).toString(
                    QtGui.QKeySequence.SequenceFormat.PortableText
                )
                if normalized and normalized == pressed:
                    return replace(action, id=action_ref)
        return None

    def _toggle_selection_action_mode(self, action) -> None:
        if self._active_selection_action_id == action.id:
            self._active_selection_action_id = None
            self.statusBar().showMessage(f"{action.label} mode OFF")
            return
        self._active_selection_action_id = action.id
        self.statusBar().showMessage(
            f"{action.label} mode ON: click a segment to apply"
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
