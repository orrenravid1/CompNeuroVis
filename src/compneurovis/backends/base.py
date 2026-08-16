from __future__ import annotations

from typing import Any, Mapping

from compneurovis.core.geometry import GeometryEntityLookup
from compneurovis.core.messages import (
    EntityClicked,
    InvokeAction,
    KeyPressed,
    Message,
    MessagePayload,
    ValueChange,
)
from compneurovis.core.runtime.actor import ActorBase
from compneurovis.core.selections import selection_after_click


def _selection_ids(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        return (str(value),)
    return tuple(str(item) for item in value)


class BackendBase(ActorBase):
    """Shared backend interaction policy.

    Entity clicks and selections are independent. ``EntityClicked`` addresses an
    authored click interaction. A backend tool may consume it; otherwise an
    optional link on that interaction applies canonical selection behavior.
    Concrete backends own model/reset logic through ``handle_backend_message``.
    """

    geometry: Any = None
    _series_sampler: Any = None

    def __init__(self) -> None:
        super().__init__()
        self._app_spec = None
        self._selection_specs: dict[str, Any] = {}
        self._entity_click_specs: dict[str, Any] = {}
        self._active_selection_id: str | None = None
        self._active_entity_click_id: str | None = None
        self._geometry_lookup: GeometryEntityLookup | None = None

    def initialize(self, app_spec) -> None:
        self._app_spec = app_spec
        self._selection_specs = {}
        self._entity_click_specs = {}
        self._active_selection_id = None
        self._active_entity_click_id = None
        self._geometry_lookup = None
        if app_spec is None:
            return
        self._selection_specs = {
            ref.id: selection for ref, selection in app_spec.iter_selections()
        }
        self._entity_click_specs = {
            ref.id: interaction for ref, interaction in app_spec.iter_entity_clicks()
        }
        self._geometry_lookup = GeometryEntityLookup(
            spec for _, spec in app_spec.iter_geometry_specs()
        )
        updates = {
            selection_id: list(selection.initial)
            for selection_id, selection in self._selection_specs.items()
        }
        self._publish_value_updates(updates)

    def handle(self, message: Message[MessagePayload]) -> None:
        payload = message.payload
        if isinstance(payload, EntityClicked):
            self._handle_entity_clicked(payload.interaction_id, payload.entity_id)
        elif isinstance(payload, ValueChange):
            self._apply_inbound_value_updates(payload.updates)
        elif isinstance(payload, InvokeAction):
            self._dispatch_action(payload.action_id, payload.payload)
        elif isinstance(payload, KeyPressed):
            self.on_key_press(payload.key, self._interaction_context())
        else:
            self.handle_backend_message(message)

    def handle_backend_message(self, message: Message[MessagePayload]) -> None:
        """Handle backend-specific commands not owned by shared interactions."""
        del message

    def _apply_inbound_value_updates(self, updates: Mapping[str, Any]) -> None:
        before = self._selection_snapshot(updates)
        self.values.apply(self, updates)
        self._notify_changed_selections(before)

    def _publish_value_updates(self, updates: Mapping[str, Any]) -> None:
        if not updates:
            return
        before = self._selection_snapshot(updates)
        for key, value in updates.items():
            self.values.set(key, value)
        self.emit_update(ValueChange(dict(updates)))
        self._notify_changed_selections(before)

    def _selection_snapshot(
        self, updates: Mapping[str, Any]
    ) -> dict[str, tuple[str, ...]]:
        return {
            key: _selection_ids(self.values.get(key))
            for key in updates
            if key in self._selection_specs
        }

    def _notify_changed_selections(
        self, before: Mapping[str, tuple[str, ...]]
    ) -> None:
        if not before:
            return
        context = self._interaction_context()
        for selection_id, previous in before.items():
            current = _selection_ids(self.values.get(selection_id))
            if current != previous:
                self.on_selection_changed(
                    selection_id,
                    previous,
                    current,
                    context,
                )

    def _handle_entity_clicked(self, interaction_id: str, entity_id: str) -> None:
        interaction = self._entity_click_specs.get(interaction_id)
        if interaction is None:
            # A backend may receive a peer fragment's command in aggregate or
            # broadcast topologies. Non-owners leave it untouched.
            return
        self._active_entity_click_id = interaction_id
        selection_id = (
            None
            if interaction.selection_id is None
            else str(interaction.selection_id)
        )
        self._active_selection_id = selection_id
        entity_id = str(entity_id)
        context = self._interaction_context()
        selection = (
            None if selection_id is None else self._selection_specs.get(selection_id)
        )
        if selection_id is not None and selection is None:
            raise ValueError(
                f"Entity-click interaction {interaction_id!r} references unknown "
                f"selection {selection_id!r}"
            )
        before = (
            () if selection_id is None else _selection_ids(self.values.get(selection_id))
        )
        consumed = self.intercept_entity_click(
            interaction_id,
            entity_id,
            context,
        )
        after_interceptor = (
            () if selection_id is None else _selection_ids(self.values.get(selection_id))
        )
        if (
            selection_id is not None
            and not consumed
            and after_interceptor == before
        ):
            selected = selection_after_click(
                before,
                entity_id,
                multiple=selection.multiple,
            )
            if _selection_ids(selected) != before:
                self._publish_value_updates({selection_id: selected})
        self.after_entity_click(interaction_id, entity_id, context)

    def intercept_entity_click(
        self,
        interaction_id: str,
        entity_id: str,
        context: Any,
    ) -> bool:
        """Return true when a tool consumes a click before default selection."""
        del interaction_id, entity_id, context
        return False

    def after_entity_click(
        self,
        interaction_id: str,
        entity_id: str,
        context: Any,
    ) -> None:
        del interaction_id, entity_id, context

    def on_selection_changed(
        self,
        selection_id: str,
        before: tuple[str, ...],
        after: tuple[str, ...],
        context: Any,
    ) -> None:
        del selection_id, before, after, context

    def on_key_press(self, key: str, context: Any) -> bool:
        del key, context
        return False

    def selection_id(self) -> str | None:
        if self._active_selection_id is not None:
            return self._active_selection_id
        if len(self._selection_specs) == 1:
            return next(iter(self._selection_specs))
        return None

    def entity_click_id(self) -> str | None:
        return self._active_entity_click_id

    def entity_info(
        self,
        entity_id: str,
        *,
        selection_id: str | None = None,
    ) -> dict[str, Any] | None:
        if self._geometry_lookup is None:
            return None
        geometry_id = None
        if selection_id is not None:
            selection = self._selection_specs.get(selection_id)
            if selection is not None:
                geometry_id = str(selection.geometry_id)
        if geometry_id is None and self._active_entity_click_id is not None:
            interaction = self._entity_click_specs.get(self._active_entity_click_id)
            if interaction is not None:
                geometry_id = str(interaction.geometry_id)
        if geometry_id is None:
            return None
        try:
            return self._geometry_lookup.entity_info(
                entity_id,
                geometry_id=geometry_id,
            )
        except KeyError:
            return None

    def _dispatch_action(self, action_id: str, payload: dict[str, Any]) -> bool:
        del action_id, payload
        return False

    def _interaction_context(self):
        from compneurovis.backends.interaction import BackendInteractionContext

        return BackendInteractionContext(self)
