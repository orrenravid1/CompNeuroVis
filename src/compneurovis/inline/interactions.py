"""Source-level control and action bindings."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from compneurovis.backends.base import BackendBase
from compneurovis.backends.interaction import BackendInteractionContext
from compneurovis.core.controls import (
    ActionSpec,
    ControlPresentationSpec,
    ControlSpec,
    ControlValueSpec,
)
from compneurovis.inline._ids import slug


@dataclass
class ControlInteraction:
    """Model accessor and canonical specification for one control."""

    name: str
    label: str
    value_spec: ControlValueSpec
    presentation: ControlPresentationSpec
    get: Callable[[], Any] | None = None
    set: Callable[[BackendInteractionContext, Any], None] | None = None
    send_to_backend: bool | None = None
    panel_id: str = "controls-panel"
    _control_id: str = field(init=False, default="")

    def _register(self, index: int) -> None:
        self._control_id = f"ctrl_{index}_{slug(self.name)}"

    def _control_spec(self) -> ControlSpec:
        return ControlSpec(
            id=self._control_id,
            label=self.label,
            value_spec=self.value_spec,
            presentation=self.presentation,
            send_to_backend=(
                self.set is not None
                if self.send_to_backend is None
                else self.send_to_backend
            ),
        )

    def apply(self, backend: BackendBase, value: Any) -> bool:
        if self.set is not None:
            self.set(backend._interaction_context(), value)
        return True


@dataclass
class ActionInteraction:
    """Named backend effect and its button or keyboard triggers."""

    name: str
    label: str
    fn: Callable[[BackendInteractionContext], None]
    shortcuts: tuple[str, ...] = ()
    show_button: bool = True
    panel_id: str | None = None
    presentation_kind: str = "button"
    presentation: Mapping[str, Any] = field(default_factory=dict)
    payload: Mapping[str, Any] = field(default_factory=dict)
    entity_click_mode: bool = False
    entity_payload_key: str = "entity_id"
    interaction_payload_key: str = "interaction_id"
    _action_id: str = field(init=False, default="")

    def _register(self, index: int) -> None:
        self._action_id = f"action_{index}_{slug(self.name)}"

    def _action_spec(self) -> ActionSpec:
        return ActionSpec(
            id=self._action_id,
            label=self.label,
            payload=self.payload,
            shortcuts=tuple(self.shortcuts),
            entity_click_mode=self.entity_click_mode,
            entity_payload_key=self.entity_payload_key,
            interaction_payload_key=self.interaction_payload_key,
            presentation_kind=self.presentation_kind,
            presentation=self.presentation,
        )


__all__ = ["ActionInteraction", "ControlInteraction"]
