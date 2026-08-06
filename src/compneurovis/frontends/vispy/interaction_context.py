from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from PyQt6 import QtCore

from compneurovis.core import AppRef, app_ref, MorphologyGeometrySpec, AppSpec
from compneurovis.frontends.vispy.view_inputs.bindings import resolve_binding

if TYPE_CHECKING:
    from compneurovis.frontends.vispy.frontend import VispyFrontendWindow


def _value_key(value: Any) -> Any:
    return (
        getattr(value, "id", value)
        if _is_selection_ref(value)
        else getattr(value, "key", value)
    )


def _window_value(window: "VispyFrontendWindow", key: Any, default: Any = None) -> Any:
    values = window.value_snapshot()
    if key in values:
        return values[key]
    return values.get(_value_key(key), default)


def _is_selection_ref(value: Any) -> bool:
    return bool(getattr(value, "_is_selection_ref", False))


def _selection_ids_from_internal(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [str(value)]
    try:
        values = list(value)
    except TypeError:
        return [str(value)]
    return [str(item) for item in values]


def _selection_to_internal(value: Any, *, select_multiple: bool) -> list[str]:
    if value is None:
        return []
    if select_multiple:
        if isinstance(value, (str, bytes)):
            raise ValueError("select_multiple=True selection expects an iterable of entity ids, not a string")
        try:
            values = list(value)
        except TypeError as exc:
            raise TypeError("select_multiple=True selection expects an iterable of entity ids") from exc
        return [str(item) for item in values]
    if isinstance(value, (list, tuple, set)):
        values = list(value)
        if not values:
            return []
        raise ValueError("single selection expects one entity id, not an iterable")
    return [str(value)]


def _selection_from_internal(value: Any, *, select_multiple: bool) -> Any:
    selected = _selection_ids_from_internal(value)
    if select_multiple:
        return selected
    return selected[0] if selected else None


class FrontendInteractionContext:
    def __init__(self, window: "VispyFrontendWindow"):
        self.window = window

    @property
    def app_spec(self) -> AppSpec | None:
        return self.window.app_spec

    @property
    def selected_entity_id(self) -> str | None:
        selection_ref = self.window._active_selection_ref
        if selection_ref is None and self.window.app_spec is not None:
            selections = tuple(self.window.app_spec.iter_selections())
            if len(selections) == 1:
                selection_ref = selections[0][0]
        if selection_ref is None:
            return None
        selected = _selection_ids_from_internal(
            _window_value(self.window, selection_ref)
        )
        return selected[-1] if selected else None

    def get_value(self, key: Any, default: Any = None) -> Any:
        if _is_selection_ref(key):
            raw = _window_value(self.window, key.id, None)
            if raw is None:
                return default
            return _selection_from_internal(raw, select_multiple=key.multiple)
        return _window_value(self.window, key, default)

    def entity_info(self, entity_id: str | None = None) -> dict[str, Any] | None:
        current_id = entity_id or self.selected_entity_id
        if current_id is None or self.window.app_spec is None:
            return None
        for _, geometry in self.window.app_spec.iter_geometry_specs():
            if not isinstance(geometry, MorphologyGeometrySpec):
                continue
            try:
                return geometry.entity_info(current_id)
            except KeyError:
                continue
        return None

    def set_value(self, key: Any, value: Any) -> None:
        resolved_key = _value_key(key)
        if _is_selection_ref(key):
            value = _selection_to_internal(value, select_multiple=key.multiple)
        self.window._apply_frontend_value(resolved_key, value)
        if self.window.refresh_planner is not None:
            self.window._apply_refresh_targets(
                self.window.refresh_planner.targets_for_value_change(resolved_key),
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
        action_ref = _resolve_action_ref(self.window.app_spec, action_id)
        if action_ref is None:
            return
        action = self.window.app_spec.action(action_ref)
        if action is None:
            return
        resolved_payload = payload if payload is not None else {
            key: resolve_binding(value, self.window.value_snapshot(), action_ref.fragment_id)
            for key, value in action.payload.items()
        }
        self.window._send_action(replace(action, id=action_ref), resolved_payload)

def _resolve_action_ref(app_spec: AppSpec, action_id: str | AppRef) -> AppRef | None:
    if isinstance(action_id, AppRef):
        return action_id if app_spec.action(action_id) is not None else None
    candidate = app_ref(action_id)
    if app_spec.action(candidate) is not None:
        return candidate
    matches = [ref for ref, _ in app_spec.iter_actions() if ref.id == action_id]
    return matches[0] if len(matches) == 1 else None
