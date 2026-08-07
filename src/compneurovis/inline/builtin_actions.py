"""Built-in actions registered through the public authoring contract."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from compneurovis.backends.interaction import BackendInteractionContext
from compneurovis.inline.action_registry import (
    ActionAuthoringContext,
    register_action,
)
from compneurovis.inline.refs import ActionRef, ButtonRef, HotkeyRef


def button(
    context: ActionAuthoringContext,
    name: str,
    *,
    label: str,
    fn: Callable[[BackendInteractionContext], None] | None = None,
    hotkey: HotkeyRef | None = None,
    presentation_kind: str = "button",
    presentation: Mapping[str, Any] | None = None,
) -> ButtonRef:
    if hotkey is not None:
        if not isinstance(hotkey, HotkeyRef):
            raise TypeError(
                f"button(..., hotkey=...) expects HotkeyRef, got {type(hotkey).__name__}"
            )
        if fn is not None:
            raise ValueError("button(..., hotkey=...) reuses its callback; omit fn")
        attached = context.present(
            hotkey,
            name,
            label=label,
            presentation_kind=presentation_kind,
            presentation=presentation,
        )
        return ButtonRef(attached._binding)
    if fn is None:
        raise ValueError("button(...) needs fn=... or hotkey=...")
    action = context.action(
        name,
        label=label,
        fn=fn,
        presentation_kind=presentation_kind,
        presentation=presentation,
    )
    return ButtonRef(action._binding)


def hotkey(
    context: ActionAuthoringContext,
    key: str | Sequence[str],
    target: ActionRef | Callable[[BackendInteractionContext], None] | None = None,
    *,
    fn: Callable[[BackendInteractionContext], None] | None = None,
) -> ActionRef:
    keys = (key,) if isinstance(key, str) else tuple(key)
    if isinstance(target, ActionRef):
        return context.add_shortcuts(target, keys)
    handler = target if callable(target) else fn
    if handler is None:
        raise ValueError("hotkey(...) needs a button reference, a callable, or fn=")
    action = context.action(
        f"hotkey_{'_'.join(keys)}",
        label="",
        fn=handler,
        shortcuts=keys,
        show_in_panel=False,
        presentation_kind="button",
    )
    return HotkeyRef(action._binding)


def register_builtin_actions() -> None:
    register_action("button", button)
    register_action("hotkey", hotkey)


__all__ = ["button", "hotkey", "register_builtin_actions"]
