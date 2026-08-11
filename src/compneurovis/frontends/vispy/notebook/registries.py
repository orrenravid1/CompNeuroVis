"""Frontend-local registries for notebook control and action presentations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from compneurovis.core.controls import ActionSpec, ControlSpec


@dataclass(frozen=True, slots=True, weakref_slot=True)
class NotebookControlRenderContext:
    """Host-independent value emission service for one notebook control."""

    _emit_value: Callable[[Any], None] = field(repr=False)

    def emit(self, value: Any) -> None:
        self._emit_value(value)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class NotebookActionRenderContext:
    """Host-independent invocation service for one notebook action."""

    _invoke_action: Callable[[], None] = field(repr=False)

    def invoke(self) -> None:
        self._invoke_action()


@dataclass(frozen=True, slots=True)
class NotebookControlPresentation:
    """Rendered ipywidget plus the frontend-driven value synchronization hook."""

    widget: Any
    _set_value: Callable[[Any], None] = field(repr=False)

    def set_value(self, value: Any) -> None:
        self._set_value(value)


NotebookControlRenderer = Callable[
    [NotebookControlRenderContext, ControlSpec, Any],
    NotebookControlPresentation,
]
NotebookActionRenderer = Callable[
    [NotebookActionRenderContext, ActionSpec, dict[Any, Any]],
    Any,
]

_control_renderers: dict[str, NotebookControlRenderer] = {}
_action_renderers: dict[str, NotebookActionRenderer] = {}


def _register(
    registry: dict[str, Any],
    kind: str,
    renderer: Any,
    *,
    override: bool,
    label: str,
) -> None:
    key = str(kind).strip()
    if not key:
        raise ValueError(f"Notebook {label} kind must be a non-empty string")
    if not callable(renderer):
        raise TypeError(f"Notebook {label} must be callable")
    current = registry.get(key)
    if current is renderer:
        return
    if current is not None and not override:
        raise ValueError(
            f"Notebook {label} kind {key!r} is already registered; "
            "pass override=True only for an intentional replacement"
        )
    registry[key] = renderer


def register_control_renderer(
    kind: str,
    renderer: NotebookControlRenderer,
    *,
    override: bool = False,
) -> None:
    """Register one ipywidgets control presentation kind."""
    _register(
        _control_renderers,
        kind,
        renderer,
        override=override,
        label="control renderer",
    )


def control_renderer(kind: str) -> NotebookControlRenderer:
    try:
        return _control_renderers[kind]
    except KeyError:
        registered = ", ".join(repr(item) for item in sorted(_control_renderers))
        suffix = f" Registered renderers are {registered}." if registered else ""
        raise ValueError(
            f"No notebook control renderer is registered for {kind!r}.{suffix}"
        ) from None


def register_action_renderer(
    kind: str,
    renderer: NotebookActionRenderer,
    *,
    override: bool = False,
) -> None:
    """Register one ipywidgets action presentation kind."""
    _register(
        _action_renderers,
        kind,
        renderer,
        override=override,
        label="action renderer",
    )


def action_renderer(kind: str) -> NotebookActionRenderer:
    try:
        return _action_renderers[kind]
    except KeyError:
        registered = ", ".join(repr(item) for item in sorted(_action_renderers))
        suffix = f" Registered renderers are {registered}." if registered else ""
        raise ValueError(
            f"No notebook action renderer is registered for {kind!r}.{suffix}"
        ) from None


__all__ = [
    "NotebookActionRenderContext",
    "NotebookActionRenderer",
    "NotebookControlPresentation",
    "NotebookControlRenderContext",
    "NotebookControlRenderer",
    "action_renderer",
    "control_renderer",
    "register_action_renderer",
    "register_control_renderer",
]
