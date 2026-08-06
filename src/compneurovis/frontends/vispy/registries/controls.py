"""Public Vispy registries for control and action presentation kinds."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from compneurovis.core.controls import ControlSpec


@dataclass(frozen=True, slots=True, weakref_slot=True)
class ActionRenderContext:
    """Host-independent invocation service for one Vispy action renderer."""

    _invoke_action: Callable[[], None] = field(repr=False)

    def invoke(self) -> None:
        """Invoke the authored action through the canonical interaction route."""
        self._invoke_action()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class ControlRenderContext:
    """Host-independent services available to one Vispy control renderer.

    Renderers construct a QWidget from the neutral ControlSpec and call
    ``emit(value)`` when its value changes. The context deliberately does not
    expose ControlsPanel: value routing, dependency refresh, and backend
    delivery remain owned by the frontend lifecycle.
    """

    _emit_value: Callable[[Any], None] = field(repr=False)

    def emit(self, value: Any) -> None:
        """Submit a user-authored value through the canonical control route."""
        self._emit_value(value)


ControlRenderer = Callable[[ControlRenderContext, ControlSpec, Any], Any]
ActionRenderer = Callable[[ActionRenderContext, Any, dict[str, Any]], Any]


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
    "ActionRenderContext",
    "ActionRenderer",
    "ActionRendererRegistration",
    "ControlRenderContext",
    "ControlRenderer",
    "ControlRendererRegistration",
    "action_renderer",
    "control_renderer",
    "register_action_renderer",
    "register_control_renderer",
]
