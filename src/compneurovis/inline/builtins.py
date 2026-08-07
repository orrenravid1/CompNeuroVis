"""Explicit composition root for first-party inline authoring capabilities."""

from __future__ import annotations

_registered = False


def register_first_party_inline() -> None:
    """Register widgets, controls, and actions shipped in the wheel."""
    global _registered
    if _registered:
        return

    from compneurovis.inline.builtin_actions import register_builtin_actions
    from compneurovis.inline.builtin_controls import register_builtin_controls
    from compneurovis.inline.builtin_widgets import register_builtin_widgets

    register_builtin_widgets()
    register_builtin_controls()
    register_builtin_actions()
    _registered = True


__all__ = ["register_first_party_inline"]
