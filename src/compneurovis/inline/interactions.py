"""Source-level control and action bindings."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from compneurovis.backends.base import BackendBase
from compneurovis.backends.interaction import BackendInteractionContext
from compneurovis.core.controls import (
    ControlPresentationSpec,
    ControlSpec,
    ControlValueSpec,
    KeyBindingSpec,
)
from compneurovis.core.messages import Clicked, PointerInteractionEvent
from compneurovis.inline._ids import slug

#: Value kind of a control that holds no state and only fires an effect.
TRIGGER_VALUE_KIND = "trigger"


ClickHandler = Callable[[BackendInteractionContext, Clicked], Any]
EntityClickHandler = Callable[[BackendInteractionContext, str], Any]
PointerInteractionHandler = Callable[
    [BackendInteractionContext, PointerInteractionEvent], Any
]


@dataclass(frozen=True, slots=True)
class ClickHandlerBinding:
    """Backend behavior attached to an exact click or a result-kind family."""

    fn: ClickHandler
    interaction_id: str | None = None
    result_kind: str | None = None

    def handles(self, interaction_id: str, result_kind: str) -> bool:
        return (
            (self.interaction_id is None or self.interaction_id == interaction_id)
            and (self.result_kind is None or self.result_kind == result_kind)
        )


@dataclass(frozen=True, slots=True)
class PointerInteractionHandlerBinding:
    """Backend behavior attached to one exact authored pointer gesture."""

    fn: PointerInteractionHandler
    interaction_id: str

    def handles(self, interaction_id: str) -> bool:
        return self.interaction_id == interaction_id


@dataclass
class ControlInteraction:
    """Model accessor and canonical specification for one control."""

    name: str
    label: str
    value_spec: ControlValueSpec
    presentation: ControlPresentationSpec
    get: Callable[[], Any] | None = None
    set: Callable[[BackendInteractionContext, Any], None] | None = None
    # A trigger control holds no state: it carries the effect to run when
    # activated, instead of a value to get and set.
    fn: Callable[[BackendInteractionContext], None] | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    send_to_backend: bool | None = None
    visible: bool = True
    panel_id: str = "controls-panel"
    _control_id: str = field(init=False, default="")
    _state_update: Callable[[Mapping[str, Any]], None] | None = field(
        init=False,
        default=None,
        repr=False,
    )

    def __post_init__(self) -> None:
        trigger = self.value_spec.kind == TRIGGER_VALUE_KIND
        if trigger and self.fn is None:
            raise ValueError(
                f"Trigger control {self.name!r} needs fn=... to invoke"
            )
        if trigger and (self.get is not None or self.set is not None):
            raise ValueError(
                f"Trigger control {self.name!r} holds no value; it takes fn=..., "
                "not get=/set="
            )
        if not trigger and self.fn is not None:
            raise ValueError(
                f"Control {self.name!r} holds a value; use set=..., not fn=..."
            )

    @property
    def is_trigger(self) -> bool:
        return self.value_spec.kind == TRIGGER_VALUE_KIND

    def _register(self, index: int) -> None:
        self._control_id = f"ctrl_{index}_{slug(self.name)}"

    def invoke(self, backend: BackendBase, payload: Mapping[str, Any]) -> bool:
        if self.fn is None:
            return False
        del payload
        self.fn(backend._interaction_context())
        return True

    def _bind_state_updates(
        self, emit: Callable[[Mapping[str, Any]], None]
    ) -> None:
        self._state_update = emit

    def set_visible(self, value: bool) -> None:
        """Change owned presentation state and publish it when running."""

        visible = bool(value)
        if self.visible == visible:
            return
        self.visible = visible
        if self._state_update is not None:
            self._state_update({"visible": visible})

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
            visible=self.visible,
        )

    def apply(self, backend: BackendBase, value: Any) -> bool:
        if self.set is not None:
            self.set(backend._interaction_context(), value)
        return True


@dataclass
class KeyBindingInteraction:
    """One or more shortcuts bound to an effect.

    Either it targets an existing invocable control, or it carries its own
    handler and is its own invocation target. It is not a panel item: it has no
    label and nothing to render, so hiding a control never disables a shortcut
    bound to it.
    """

    name: str
    shortcuts: tuple[str, ...]
    fn: Callable[[BackendInteractionContext], None] | None = None
    target: "ControlInteraction | None" = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    _binding_id: str = field(init=False, default="")

    def __post_init__(self) -> None:
        if not self.shortcuts:
            raise ValueError(f"Key binding {self.name!r} needs at least one key")
        if (self.fn is None) == (self.target is None):
            raise ValueError(
                f"Key binding {self.name!r} needs exactly one of fn=... or an "
                "existing control to target"
            )

    def _register(self, index: int) -> None:
        self._binding_id = f"key_{index}_{slug(self.name)}"

    def _invokes_id(self) -> str:
        # Resolved late: a targeted control's id is assigned when it is added,
        # so reading it here never depends on authoring order.
        return self._binding_id if self.target is None else self.target._control_id

    def _key_binding_spec(self) -> KeyBindingSpec:
        return KeyBindingSpec(
            id=self._binding_id,
            shortcuts=tuple(self.shortcuts),
            invokes=self._invokes_id(),
            payload=self.payload,
        )

    def invoke(self, backend: BackendBase, payload: Mapping[str, Any]) -> bool:
        if self.fn is None:
            return False
        del payload
        self.fn(backend._interaction_context())
        return True


__all__ = [
    "TRIGGER_VALUE_KIND",
    "KeyBindingInteraction",
    "ClickHandler",
    "ClickHandlerBinding",
    "ControlInteraction",
    "EntityClickHandler",
    "PointerInteractionHandler",
    "PointerInteractionHandlerBinding",
]
