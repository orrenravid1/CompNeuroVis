from __future__ import annotations

from typing import Any, Mapping

from compneurovis.core.geometry import GeometryEntityLookup
from compneurovis.core.messages import (
    Clicked,
    PointerInteractionEvent,
    InvokeAction,
    Message,
    MessagePayload,
    ValueChange,
)
from compneurovis.core.runtime.actor import ActorBase
from compneurovis.core.selections import selection_after_click


def _selection_values(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)):
        return (value,)
    try:
        return tuple(value)
    except TypeError:
        return (value,)


class BackendBase(ActorBase):
    """Shared backend interaction policy.

    Clicks and selections are independent. ``Clicked`` addresses an authored
    click interaction and carries the renderer-resolved, data-only value. A
    backend tool may consume it; otherwise an optional link on that interaction
    applies canonical selection behavior. Entity ids are one result kind.
    Concrete backends own model/reset logic through ``handle_backend_message``.
    """

    geometry: Any = None
    _series_sampler: Any = None

    def __init__(self) -> None:
        super().__init__()
        self._app_spec = None
        self._selection_specs: dict[str, Any] = {}
        self._hit_target_specs: dict[str, Any] = {}
        self._click_specs: dict[str, Any] = {}
        self._pointer_interaction_specs: dict[str, Any] = {}
        self._active_selection_id: str | None = None
        self._active_hit_target_id: str | None = None
        self._active_click_event: Clicked | None = None
        self._active_pointer_interaction_id: str | None = None
        self._geometry_lookup: GeometryEntityLookup | None = None

    def initialize(self, app_spec) -> None:
        self._app_spec = app_spec
        self._selection_specs = {}
        self._hit_target_specs = {}
        self._click_specs = {}
        self._pointer_interaction_specs = {}
        self._active_selection_id = None
        self._active_hit_target_id = None
        self._active_click_event = None
        self._active_pointer_interaction_id = None
        self._geometry_lookup = None
        if app_spec is None:
            return
        self._selection_specs = {
            ref.id: selection for ref, selection in app_spec.iter_selections()
        }
        self._hit_target_specs = {
            ref.id: target for ref, target in app_spec.iter_hit_targets()
        }
        self._click_specs = {
            ref.id: interaction for ref, interaction in app_spec.iter_clicks()
        }
        self._pointer_interaction_specs = {
            ref.id: interaction
            for ref, interaction in app_spec.iter_pointer_interactions()
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
        if isinstance(payload, Clicked):
            self._handle_clicked(payload)
        elif isinstance(payload, PointerInteractionEvent):
            self._handle_pointer_interaction(payload)
        elif isinstance(payload, ValueChange):
            self._apply_inbound_value_updates(payload.updates)
        elif isinstance(payload, InvokeAction):
            self._dispatch_action(payload.action_id, payload.payload)
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
    ) -> dict[str, tuple[Any, ...]]:
        return {
            key: _selection_values(self.values.get(key))
            for key in updates
            if key in self._selection_specs
        }

    def _notify_changed_selections(
        self, before: Mapping[str, tuple[Any, ...]]
    ) -> None:
        if not before:
            return
        context = self._interaction_context()
        for selection_id, previous in before.items():
            current = _selection_values(self.values.get(selection_id))
            if current != previous:
                self.on_selection_changed(
                    selection_id,
                    previous,
                    current,
                    context,
                )

    def _handle_clicked(self, event: Clicked) -> None:
        interaction_id = event.interaction_id
        interaction = self._click_specs.get(interaction_id)
        if interaction is None:
            # A backend may receive a peer fragment's command in aggregate or
            # broadcast topologies. Non-owners leave it untouched.
            return
        if interaction.result_kind == "entity" and not isinstance(event.value, str):
            raise TypeError(
                f"Entity click {interaction_id!r} must resolve to a string id"
            )
        selection_id = (
            None
            if interaction.selection_id is None
            else str(interaction.selection_id)
        )
        selection = (
            None if selection_id is None else self._selection_specs.get(selection_id)
        )
        if selection_id is not None and selection is None:
            raise ValueError(
                f"Click interaction {interaction_id!r} references unknown "
                f"selection {selection_id!r}"
            )
        previous = (
            self._active_hit_target_id,
            self._active_click_event,
            self._active_pointer_interaction_id,
            self._active_selection_id,
        )
        self._active_hit_target_id = str(interaction.hit_target_id)
        self._active_click_event = event
        self._active_pointer_interaction_id = None
        self._active_selection_id = selection_id
        try:
            context = self._interaction_context()
            before = (
                ()
                if selection_id is None
                else _selection_values(self.values.get(selection_id))
            )
            consumed = self.intercept_click(event, context)
            after_interceptor = (
                ()
                if selection_id is None
                else _selection_values(self.values.get(selection_id))
            )
            if (
                selection_id is not None
                and not consumed
                and after_interceptor == before
            ):
                selected = selection_after_click(
                    before,
                    event.value,
                    multiple=selection.multiple,
                )
                if _selection_values(selected) != before:
                    self._publish_value_updates({selection_id: selected})
            self.after_click(event, context)
        finally:
            (
                self._active_hit_target_id,
                self._active_click_event,
                self._active_pointer_interaction_id,
                self._active_selection_id,
            ) = previous

    def _handle_pointer_interaction(
        self, event: PointerInteractionEvent
    ) -> None:
        pointer = self._pointer_interaction_specs.get(event.interaction_id)
        if pointer is None:
            # Peer-fragment commands are not owned by this backend.
            return
        target_id = str(pointer.hit_target_id)
        target = self._hit_target_specs.get(target_id)
        if target is None:
            raise ValueError(
                f"Pointer interaction {event.interaction_id!r} references unknown "
                f"hit target {target_id!r}"
            )
        if (
            pointer.result_kind == "entity"
            and event.value is not None
            and not isinstance(event.value, str)
        ):
            raise TypeError(
                f"Entity pointer interaction {event.interaction_id!r} must "
                "resolve to a string id or None"
            )
        previous = (
            self._active_hit_target_id,
            self._active_click_event,
            self._active_pointer_interaction_id,
            self._active_selection_id,
        )
        self._active_hit_target_id = target_id
        self._active_click_event = None
        self._active_pointer_interaction_id = event.interaction_id
        self._active_selection_id = None
        try:
            self.on_pointer_interaction(event, self._interaction_context())
        finally:
            (
                self._active_hit_target_id,
                self._active_click_event,
                self._active_pointer_interaction_id,
                self._active_selection_id,
            ) = previous

    def intercept_click(self, event: Clicked, context: Any) -> bool:
        """Return true when a tool consumes a click before default selection."""
        del event, context
        return False

    def after_click(self, event: Clicked, context: Any) -> None:
        del event, context

    def on_pointer_interaction(
        self, event: PointerInteractionEvent, context: Any
    ) -> bool:
        """Handle a captured pointer phase; pointer gestures never imply selection."""
        del event, context
        return False

    def on_selection_changed(
        self,
        selection_id: str,
        before: tuple[Any, ...],
        after: tuple[Any, ...],
        context: Any,
    ) -> None:
        del selection_id, before, after, context

    def selection_id(self) -> str | None:
        if self._active_selection_id is not None:
            return self._active_selection_id
        if len(self._selection_specs) == 1:
            return next(iter(self._selection_specs))
        return None

    def click_id(self) -> str | None:
        return (
            None
            if self._active_click_event is None
            else self._active_click_event.interaction_id
        )

    def click_value(self) -> Any:
        return (
            None
            if self._active_click_event is None
            else self._active_click_event.value
        )

    def click_gesture(self) -> Any:
        return (
            None
            if self._active_click_event is None
            else self._active_click_event.gesture
        )

    def entity_click_id(self) -> str | None:
        click_id = self.click_id()
        if click_id is None:
            return None
        interaction = self._click_specs.get(click_id)
        return (
            click_id
            if interaction is not None and interaction.result_kind == "entity"
            else None
        )

    def hit_target_id(self) -> str | None:
        return self._active_hit_target_id

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
                if selection.target_type == "geometry":
                    geometry_id = str(selection.target_id)
                else:
                    return None
        if (
            geometry_id is None
            and selection_id is None
            and self._active_click_event is not None
        ):
            interaction = self._click_specs.get(
                self._active_click_event.interaction_id
            )
            if interaction is not None and interaction.geometry_scope_id is not None:
                geometry_id = str(interaction.geometry_scope_id)
        if (
            geometry_id is None
            and self._active_pointer_interaction_id is not None
        ):
            pointer = self._pointer_interaction_specs.get(
                self._active_pointer_interaction_id
            )
            if pointer is not None and pointer.geometry_scope_id is not None:
                geometry_id = str(pointer.geometry_scope_id)
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
