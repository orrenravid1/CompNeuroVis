"""Source-level control and action bindings."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from compneurovis.backends.base import BackendBase
from compneurovis.backends.interaction import BackendInteractionContext
from compneurovis.core.controls import (
    ActionSpec,
    ControlPresentationSpec,
    ControlSpec,
    ControlValueSpec,
    ScalarValueSpec,
)
from compneurovis.inline._ids import slug


@dataclass
class ControlInteraction:
    """Model accessor and canonical specification for one control."""

    name: str
    label: str
    get: Callable[[], Any] | None = None
    set: Callable[[BackendInteractionContext, Any], None] | None = None
    min: float = 0.0
    max: float = 1.0
    default: Any = 0.0
    value_spec: ControlValueSpec | None = None
    presentation: ControlPresentationSpec | None = None
    send_to_backend: bool | None = None
    panel_id: str = "controls-panel"
    _control_id: str = field(init=False, default="")

    def _register(self, index: int) -> None:
        self._control_id = f"ctrl_{index}_{slug(self.name)}"

    def _control_spec(self) -> ControlSpec:
        if self.value_spec is not None:
            value_spec = self.value_spec
        else:
            default = self.get() if self.get is not None else self.default
            value_spec = ScalarValueSpec(default=default, min=self.min, max=self.max)
        return ControlSpec(
            id=self._control_id,
            label=self.label,
            value_spec=value_spec,
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
    _action_id: str = field(init=False, default="")

    def _register(self, index: int) -> None:
        self._action_id = f"action_{index}_{slug(self.name)}"

    def _action_spec(self) -> ActionSpec:
        return ActionSpec(
            id=self._action_id,
            label=self.label,
            shortcuts=tuple(self.shortcuts),
        )


__all__ = ["ActionInteraction", "ControlInteraction"]
