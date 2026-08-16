"""Shared VisPy scene-rendering conventions.

VisPy draws sibling scene nodes in ascending ``Node.order``. Transparent
geometry therefore must follow opaque content, while depth-independent labels
and guides must follow both. Keep those relative relationships here rather than
spreading unexplained order literals through component renderers.

VisPy GL state is context-global and is not restored after every visual. A
renderer may use a standard preset such as ``"translucent"``, but it must not
casually change persistent state such as ``depth_mask``. In particular, setting
``depth_mask=False`` on an overlay can corrupt later ``InstancedMesh`` draws.
Prefer the smallest preset/configuration that works and validate it alongside
other visuals sharing the canvas.

Passive scene hover is another VisPy-specific integration detail. SceneCanvas
suppresses unpressed mouse-move delivery by default and exposes only the private
``_send_hover_events`` switch. Access is centralized here so the generic pointer
observation contract does not depend on that private name.
"""

from __future__ import annotations

from enum import IntEnum


class SceneRenderLayer(IntEnum):
    """Semantic draw layers for sibling nodes in a shared VisPy scene."""

    CONTENT = 0
    TRANSLUCENT_OVERLAY = 100
    ANNOTATION_FILL = 200
    ANNOTATION_FOREGROUND = 300


def set_passive_hover_delivery(canvas, active: bool) -> None:
    """Enable VisPy scene hover delivery while a pointer observer needs it."""

    if not hasattr(canvas, "_send_hover_events"):
        raise RuntimeError(
            "This VisPy SceneCanvas does not expose passive hover delivery"
        )
    canvas._send_hover_events = bool(active)


__all__ = [
    "SceneRenderLayer",
]
