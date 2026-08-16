"""Public authoring registry for named source-level action kinds."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from compneurovis.backends.interaction import BackendInteractionContext
from compneurovis.inline._ids import authoring_method_name
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
        entity_click_mode: bool = False,
        entity_payload_key: str = "entity_id",
        interaction_payload_key: str = "interaction_id",
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
            entity_click_mode=entity_click_mode,
            entity_payload_key=entity_payload_key,
            interaction_payload_key=interaction_payload_key,
            panel_id=self.panel_id,
        )

    def present(
        self,
        target: ActionRef,
        name: str,
        *,
        label: str,
        presentation_kind: str,
        presentation: Mapping[str, Any] | None = None,
    ) -> ActionRef:
        """Attach one visible presentation to an existing action."""
        return self._source._attach_action_presentation(
            target,
            name=name,
            label=label,
            presentation_kind=presentation_kind,
            presentation=presentation or {},
            panel_id=self.panel_id,
        )

    def add_shortcuts(
        self,
        target: ActionRef,
        shortcuts: Sequence[str],
    ) -> ActionRef:
        """Attach keyboard shortcuts to an existing action."""
        return self._source._attach_action_shortcuts(target, tuple(shortcuts))


ActionAuthoringFactory = Callable[..., ActionRef]
_action_factories: dict[str, ActionAuthoringFactory] = {}


def register_action(
    name: str,
    factory: ActionAuthoringFactory,
    *,
    override: bool = False,
) -> None:
    """Expose an action as dynamic `source.<name>` and `controls.<name>`."""
    key = authoring_method_name(name, label="Action name")
    if not callable(factory):
        raise TypeError("Action factory must be callable")
    current = _action_factories.get(key)
    if current is factory:
        return
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
