"""Built-in actions registered through the public authoring contract."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from compneurovis.backends.interaction import BackendInteractionContext
from compneurovis.inline.action_registry import (
    ActionAuthoringContext,
    register_action,
)
from compneurovis.inline.refs import ActionRef


def button(
    context: ActionAuthoringContext,
    name: str,
    *,
    label: str,
    fn: Callable[[BackendInteractionContext], None],
    presentation_kind: str = "button",
    presentation: Mapping[str, Any] | None = None,
) -> ActionRef:
    return context.action(
        name,
        label=label,
        fn=fn,
        presentation_kind=presentation_kind,
        presentation=presentation,
    )


def hotkey(
    context: ActionAuthoringContext,
    key: str | Sequence[str],
    target: ActionRef | Callable[[BackendInteractionContext], None] | None = None,
    *,
    fn: Callable[[BackendInteractionContext], None] | None = None,
) -> ActionRef:
    keys = (key,) if isinstance(key, str) else tuple(key)
    if isinstance(target, ActionRef):
        binding = target._binding
        binding.shortcuts = tuple(binding.shortcuts) + keys
        return target
    handler = target if callable(target) else fn
    if handler is None:
        raise ValueError("hotkey(...) needs a button reference, a callable, or fn=")
    return context.action(
        f"hotkey_{'_'.join(keys)}",
        label="",
        fn=handler,
        shortcuts=keys,
        show_in_panel=False,
        presentation_kind="button",
    )


def register_builtin_actions() -> None:
    register_action("button", button)
    register_action("hotkey", hotkey)


__all__ = ["button", "hotkey", "register_builtin_actions"]
