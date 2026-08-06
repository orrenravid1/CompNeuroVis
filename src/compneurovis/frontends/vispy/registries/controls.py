"""Public Vispy registries for control and action presentation kinds."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


ControlRenderer = Callable[[Any, Any, Any], Any]
ActionRenderer = Callable[[Any, Any, dict[str, Any]], Any]


@dataclass(frozen=True, slots=True)
class ControlRendererRegistration:
    factory: ControlRenderer
    full_width: bool = False


@dataclass(frozen=True, slots=True)
class ActionRendererRegistration:
    factory: ActionRenderer
    full_width: bool = False


_control_renderers: dict[str, ControlRendererRegistration] = {}
_action_renderers: dict[str, ActionRendererRegistration] = {}


def _register(
    registry: dict[str, Any],
    kind: str,
    registration: Any,
    *,
    override: bool,
    label: str,
) -> None:
    key = str(kind).strip()
    if not key:
        raise ValueError(f"{label} kind must be a non-empty string")
    current = registry.get(key)
    if current == registration:
        return
    if current is not None and not override:
        raise ValueError(
            f"Vispy {label} kind {key!r} is already registered; "
            "pass override=True only for an intentional replacement"
        )
    registry[key] = registration


def register_control_renderer(
    kind: str,
    factory: ControlRenderer,
    *,
    full_width: bool = False,
    override: bool = False,
) -> None:
    """Register the Vispy renderer for one control presentation kind."""
    if not callable(factory):
        raise TypeError("Control renderer factory must be callable")
    _register(
        _control_renderers,
        kind,
        ControlRendererRegistration(factory, full_width),
        override=override,
        label="control renderer",
    )


def control_renderer(kind: str) -> ControlRendererRegistration:
    try:
        return _control_renderers[kind]
    except KeyError:
        registered = ", ".join(repr(item) for item in sorted(_control_renderers))
        suffix = f" Registered renderers are {registered}." if registered else ""
        raise ValueError(
            f"No Vispy control renderer is registered for {kind!r}.{suffix}"
        ) from None


def register_action_renderer(
    kind: str,
    factory: ActionRenderer,
    *,
    full_width: bool = False,
    override: bool = False,
) -> None:
    """Register the Vispy renderer for one action presentation kind."""
    if not callable(factory):
        raise TypeError("Action renderer factory must be callable")
    _register(
        _action_renderers,
        kind,
        ActionRendererRegistration(factory, full_width),
        override=override,
        label="action renderer",
    )


def action_renderer(kind: str) -> ActionRendererRegistration:
    try:
        return _action_renderers[kind]
    except KeyError:
        registered = ", ".join(repr(item) for item in sorted(_action_renderers))
        suffix = f" Registered renderers are {registered}." if registered else ""
        raise ValueError(
            f"No Vispy action renderer is registered for {kind!r}.{suffix}"
        ) from None


__all__ = [
    "ActionRenderer",
    "ActionRendererRegistration",
    "ControlRenderer",
    "ControlRendererRegistration",
    "action_renderer",
    "control_renderer",
    "register_action_renderer",
    "register_control_renderer",
]
