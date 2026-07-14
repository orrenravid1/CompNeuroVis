from __future__ import annotations

from typing import Any


_INTERACTION_HANDLER_NAMES = ("on_action", "on_key_press", "on_entity_clicked")


def resolve_interaction_target_source(source: Any | None) -> Any | None:
    if source is None:
        return None
    if isinstance(source, type):
        return source()
    if callable(source) and not any(hasattr(source, name) for name in _INTERACTION_HANDLER_NAMES):
        return source()
    return source


__all__ = ["resolve_interaction_target_source"]
