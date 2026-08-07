"""Frontend-local render configs and their reconstruction registry.

Surface/morphology author as ``ViewSpec(kind=...)`` but render through a
typed render-config the vispy frontend reconstructs at the refresh boundary. Each
such view kind registers its ``from_view`` builder from its own frontend module
(like a third-party kind would); this registry holds no per-kind knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from compneurovis.core import ViewSpec


_VIEW_RENDER_CONFIGS: "dict[str, Callable[[Any], Any]]" = {}


def _same_callable(left: Callable[..., Any], right: Callable[..., Any]) -> bool:
    """Identity comparison that also recognizes repeated bound-method lookup."""
    if left is right:
        return True
    left_function = getattr(left, "__func__", None)
    return (
        left_function is not None
        and left_function is getattr(right, "__func__", None)
        and getattr(left, "__self__", None) is getattr(right, "__self__", None)
    )


@dataclass(frozen=True, slots=True)
class ViewRenderConfig:
    """Common identity and presentation state for a Vispy render config."""

    id: str
    title: Any = ""


def register_view_render_config(
    kind: str,
    from_view: "Callable[[Any], Any]",
    *,
    override: bool = False,
) -> None:
    """Register the render-config reconstructor for an authored view ``kind``."""
    normalized = _validate_view_render_config_registration(
        kind,
        from_view,
        override=override,
    )
    _commit_view_render_config_registration(normalized, from_view)


def _validate_view_render_config_registration(
    kind: str,
    from_view: "Callable[[Any], Any]",
    *,
    override: bool = False,
) -> str:
    """Validate without mutating so composite registrations can preflight."""
    normalized = str(kind).strip()
    if not normalized:
        raise ValueError("View render-config kind cannot be empty")
    if not callable(from_view):
        raise TypeError("View render-config builder must be callable")
    current = _VIEW_RENDER_CONFIGS.get(normalized)
    if current is not None and _same_callable(current, from_view):
        return normalized
    if current is not None and not override:
        raise ValueError(
            f"Vispy view render-config {normalized!r} is already registered; "
            "pass override=True only for an intentional replacement"
        )
    return normalized


def _commit_view_render_config_registration(
    normalized: str,
    from_view: "Callable[[Any], Any]",
) -> None:
    """Commit a preflighted registration; this operation cannot raise."""
    _VIEW_RENDER_CONFIGS[normalized] = from_view


def view_render_config(view):
    """Rebuild the typed render-config for an authored view.

    Any view without a registered reconstructor (2-D views, already-typed
    render-configs) passes through unchanged, so callers can apply this at every
    ``app_spec.view(...)`` boundary.
    """
    if isinstance(view, ViewSpec):
        builder = _VIEW_RENDER_CONFIGS.get(view.kind)
        if builder is not None:
            return builder(view)
    return view


__all__ = [
    "ViewRenderConfig",
    "register_view_render_config",
    "view_render_config",
]
