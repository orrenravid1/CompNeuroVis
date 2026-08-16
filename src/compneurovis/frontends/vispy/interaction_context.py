from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PyQt6 import QtCore

from compneurovis.core import AppRef, app_ref, AppSpec
from compneurovis.core.geometry import geometry_entity_info
from compneurovis.frontends.vispy.bindings import resolve_binding
from compneurovis.frontends.vispy.registries.controls import ResolvedAction

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

    def _selection_ref(self, selection: Any = None) -> AppRef | None:
        if selection is not None:
            candidate = (
                selection
                if isinstance(selection, AppRef)
                else app_ref(_value_key(selection))
            )
            return (
                candidate
                if self.window.app_spec is not None
                and self.window.app_spec.selection(candidate) is not None
                else None
            )
        selection_ref = self.window._active_selection_ref
        if selection_ref is None and self.window.app_spec is not None:
            selections = tuple(self.window.app_spec.iter_selections())
            if len(selections) == 1:
                selection_ref = selections[0][0]
        return selection_ref

    @property
    def selected_entity_id(self) -> str | None:
        selection_ref = self._selection_ref()
        if selection_ref is None:
            return None
        selected = _selection_ids_from_internal(
            _window_value(self.window, selection_ref)
        )
        return selected[-1] if selected else None

    @property
    def entity_click_id(self) -> AppRef | None:
        """Authored click interaction currently being handled, if any."""
        return self.window._active_entity_click_ref

    def get_value(self, key: Any, default: Any = None) -> Any:
        if _is_selection_ref(key):
            raw = _window_value(self.window, key.id, None)
            if raw is None:
                return default
            return _selection_from_internal(raw, select_multiple=key.multiple)
        return _window_value(self.window, key, default)

    def entity_info(
        self,
        entity_id: str | None = None,
        *,
        selection: Any = None,
    ) -> dict[str, Any] | None:
        current_id = entity_id or self.selected_entity_id
        if current_id is None or self.window.app_spec is None:
            return None
        if selection is not None:
            selection_ref = self._selection_ref(selection)
        elif self.window._active_entity_click_ref is not None:
            # An active pure click owns exact geometry and must not inherit an
            # unrelated sole-selection fallback.
            selection_ref = self.window._active_selection_ref
        else:
            selection_ref = self._selection_ref()
        if selection_ref is not None:
            selection_spec = self.window.app_spec.selection(selection_ref)
            if selection_spec is None:
                return None
            geometry_ref = app_ref(
                selection_spec.geometry_id,
                fragment_id=selection_ref.fragment_id,
            )
        else:
            interaction_ref = self.window._active_entity_click_ref
            interaction = (
                None
                if interaction_ref is None
                else self.window.app_spec.entity_click(interaction_ref)
            )
            if interaction is None:
                return None
            geometry_ref = app_ref(
                interaction.geometry_id,
                fragment_id=interaction_ref.fragment_id,
            )
        geometry = self.window.app_spec.geometry(geometry_ref)
        return (
            None
            if geometry is None
            else geometry_entity_info(geometry, current_id)
        )

    def set_value(self, key: Any, value: Any) -> None:
        resolved_key = _value_key(key)
        if _is_selection_ref(key):
            value = _selection_to_internal(value, select_multiple=key.multiple)
        self.window._apply_frontend_value(resolved_key, value)
        if self.window.refresh_planner is not None:
            self.window._apply_refresh_targets(
                self.window.refresh_planner.targets_for_value_change(resolved_key),
                force_scene=True,
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
        self.window._send_action(
            ResolvedAction(ref=action_ref, spec=action), resolved_payload
        )

def _resolve_action_ref(app_spec: AppSpec, action_id: str | AppRef) -> AppRef | None:
    if isinstance(action_id, AppRef):
        return action_id if app_spec.action(action_id) is not None else None
    candidate = app_ref(action_id)
    if app_spec.action(candidate) is not None:
        return candidate
    matches = [ref for ref, _ in app_spec.iter_actions() if ref.id == action_id]
    return matches[0] if len(matches) == 1 else None
