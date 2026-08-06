"""Public authoring registry for named source-level action kinds."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from compneurovis.backends.interaction import BackendInteractionContext
from compneurovis.inline.refs import ActionRef


@dataclass(frozen=True)
class ActionAuthoringContext:
    """Stable declaration surface passed to registered action factories."""

    _source: Any
    panel_id: str | None

    def action(
        self,
        name: str,
        *,
        label: str,
        fn: Callable[[BackendInteractionContext], None],
        shortcuts: Sequence[str] = (),
        show_in_panel: bool = True,
        presentation_kind: str,
        presentation: Mapping[str, Any] | None = None,
        payload: Mapping[str, Any] | None = None,
        selection_mode: bool = False,
        selection_payload_key: str = "entity_id",
    ) -> ActionRef:
        return self._source._register_action(
            name,
            label=label,
            fn=fn,
            shortcuts=tuple(shortcuts),
            show_in_panel=show_in_panel,
            presentation_kind=presentation_kind,
            presentation=presentation or {},
            payload=payload or {},
            selection_mode=selection_mode,
            selection_payload_key=selection_payload_key,
            panel_id=self.panel_id,
        )


ActionAuthoringFactory = Callable[..., ActionRef]
_action_factories: dict[str, ActionAuthoringFactory] = {}


def register_action(
    name: str,
    factory: ActionAuthoringFactory,
    *,
    override: bool = False,
) -> None:
    """Expose an action as dynamic `source.<name>` and `controls.<name>`."""
    key = str(name).strip()
    if not key:
        raise ValueError("Action name must be a non-empty string")
    if key.startswith("_"):
        raise ValueError("Action name cannot start with '_'")
    if not callable(factory):
        raise TypeError("Action factory must be callable")
    from compneurovis.inline.control_registry import registered_controls

    if key in registered_controls():
        raise ValueError(
            f"source.{key}(...) is already an authoring name; choose another action name"
        )
    from compneurovis.inline.widget_registry import widget_name_taken

    if widget_name_taken(key):
        raise ValueError(
            f"source.{key}(...) is already an authoring name; choose another action name"
        )
    current = _action_factories.get(key)
    if current is factory:
        return
    if current is not None and not override:
        raise ValueError(
            f"Action authoring kind {key!r} is already registered; "
            "pass override=True only for an intentional replacement"
        )
    _action_factories[key] = factory


def action_factory(name: str) -> ActionAuthoringFactory:
    try:
        return _action_factories[name]
    except KeyError:
        registered = ", ".join(repr(item) for item in registered_actions())
        suffix = f" Registered actions are {registered}." if registered else ""
        raise AttributeError(f"No action kind {name!r} is registered.{suffix}") from None


def registered_actions() -> tuple[str, ...]:
    return tuple(sorted(_action_factories))


__all__ = [
    "ActionAuthoringContext",
    "ActionAuthoringFactory",
    "action_factory",
    "register_action",
    "registered_actions",
]
