"""Registry that rebuilds a view's typed render-config from an authored view.

Surface/morphology author as ``ExtensionViewSpec(kind=...)`` but render through a
typed render-config the vispy frontend reconstructs at the refresh boundary. Each
such view kind registers its ``from_extension`` builder from its own frontend module
(like a third-party kind would); this registry holds no per-kind knowledge.
"""

from __future__ import annotations

from typing import Any, Callable

from compneurovis.core import ExtensionViewSpec


_VIEW_RENDER_CONFIGS: "dict[str, Callable[[Any], Any]]" = {}


def register_view_render_config(kind: str, from_extension: "Callable[[Any], Any]") -> None:
    """Register the render-config reconstructor for an authored view ``kind``."""
    _VIEW_RENDER_CONFIGS[kind] = from_extension


def view_render_config(view):
    """Rebuild the typed render-config for an authored extension view.

    Any view without a registered reconstructor (2-D extension views, already-typed
    render-configs) passes through unchanged, so callers can apply this at every
    ``app_spec.view(...)`` boundary.
    """
    if isinstance(view, ExtensionViewSpec):
        builder = _VIEW_RENDER_CONFIGS.get(view.kind)
        if builder is not None:
            return builder(view)
    return view
