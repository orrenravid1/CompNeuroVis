from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PyQt6 import QtCore

from compneurovis.core import MorphologyGeometrySpec, AppSpec
from compneurovis.frontends.vispy.refresh_planning import resolve_value

if TYPE_CHECKING:
    from compneurovis.frontends.vispy.frontend import VispyFrontendWindow


class FrontendInteractionContext:
    def __init__(self, window: "VispyFrontendWindow"):
        self.window = window

    @property
    def app_spec(self) -> AppSpec | None:
        return self.window.app_spec

    @property
    def selected_entity_id(self) -> str | None:
        value = self.window.state.get("selected_entity_id")
        return str(value) if value is not None else None

    def state(self, key: str, default: Any = None) -> Any:
        return self.window.state.get(key, default)

    def entity_info(self, entity_id: str | None = None) -> dict[str, Any] | None:
        current_id = entity_id or self.selected_entity_id
        if current_id is None or self.window.app_spec is None:
            return None
        for geometry in self.window.app_spec.data.geometries.values():
            if not isinstance(geometry, MorphologyGeometrySpec):
                continue
            try:
                return geometry.entity_info(current_id)
            except KeyError:
                continue
        return None

    def set_state(self, key: str, value: Any) -> None:
        self.window.state[key] = value
        if self.window.refresh_planner is not None:
            self.window._apply_refresh_targets(
                self.window.refresh_planner.targets_for_state_change(key),
                force_view_3d=True,
            )

    def show_status(self, message: str, timeout_ms: int | None = None) -> None:
        self.window.statusBar().showMessage(message)
        if timeout_ms is not None:
            QtCore.QTimer.singleShot(timeout_ms, self.window.statusBar().clearMessage)

    def clear_status(self) -> None:
        self.window.statusBar().clearMessage()

    def invoke_action(self, action_id: str, payload: dict[str, Any] | None = None) -> None:
        if self.window.app_spec is None:
            return
        action = self.window.app_spec.interactions.actions.get(action_id)
        if action is None:
            return
        resolved_payload = payload if payload is not None else {
            key: resolve_value(value, self.window.state)
            for key, value in action.payload.items()
        }
        self.window._send_action(action, resolved_payload)

    def set_control(self, control_id: str, value: Any) -> None:
        if self.window.app_spec is None:
            return
        control = self.window.app_spec.interactions.controls.get(control_id)
        if control is None:
            return
        self.window._on_control_changed(control, value)
