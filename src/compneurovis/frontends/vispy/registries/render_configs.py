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


@dataclass(frozen=True, slots=True)
class ViewRenderConfig:
    """Common identity and presentation state for a Vispy render config."""

    id: str
    title: Any = ""


def register_view_render_config(kind: str, from_view: "Callable[[Any], Any]") -> None:
    """Register the render-config reconstructor for an authored view ``kind``."""
    _VIEW_RENDER_CONFIGS[kind] = from_view


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
