"""Capability-scoped Vispy registries for owner-authored visual layers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


SCENE_3D_LAYER_CAPABILITY = "scene3d.layers/v1"
PLOT_2D_LAYER_CAPABILITY = "plot2d.layers/v1"

VisualContributionRendererFactory = Callable[..., Any]


@dataclass(frozen=True, slots=True)
class VisualContributionRendererRegistration:
    factory: VisualContributionRendererFactory


@dataclass(frozen=True)
class VisualContributionHostContext:
    """Narrow target-host surface passed to a contribution renderer factory."""

    capability: str
    panel_id: str
    view_id: Any | None
    host: Any
    surface: Any
    pointer_observations: Any | None = None


_renderers: dict[
    tuple[str, str], VisualContributionRendererRegistration
] = {}


def register_visual_contribution_renderer(
    capability: str,
    kind: str,
    factory: VisualContributionRendererFactory,
    *,
    override: bool = False,
) -> None:
    """Register one renderer within one explicit target-host capability."""
    capability_key = str(capability).strip()
    kind_key = str(kind).strip()
    if not capability_key or not kind_key:
        raise ValueError("Visual contribution capability and kind cannot be empty")
    if not callable(factory):
        raise TypeError("Visual contribution renderer factory must be callable")
    key = (capability_key, kind_key)
    registration = VisualContributionRendererRegistration(factory)
    current = _renderers.get(key)
    if current == registration:
        return
    if current is not None and not override:
        raise ValueError(
            f"Vispy visual contribution {kind_key!r} is already registered for "
            f"capability {capability_key!r}; pass override=True only for an "
            "intentional replacement"
        )
    _renderers[key] = registration


def register_scene_contribution(
    kind: str,
    factory: VisualContributionRendererFactory,
    *,
    override: bool = False,
) -> None:
    """Register a contribution rendered inside a shared Scene3D host."""
    register_visual_contribution_renderer(
        SCENE_3D_LAYER_CAPABILITY, kind, factory, override=override
    )


def register_plot_contribution(
    kind: str,
    factory: VisualContributionRendererFactory,
    *,
    override: bool = False,
) -> None:
    """Register a contribution rendered inside a shared Plot2D host."""
    register_visual_contribution_renderer(
        PLOT_2D_LAYER_CAPABILITY, kind, factory, override=override
    )


def visual_contribution_renderer(
    capability: str, kind: str
) -> VisualContributionRendererRegistration:
    key = (capability, kind)
    try:
        return _renderers[key]
    except KeyError:
        supported = ", ".join(
            repr(candidate_kind)
            for candidate_capability, candidate_kind in sorted(_renderers)
            if candidate_capability == capability
        )
        suffix = f" Registered kinds are {supported}." if supported else ""
        raise LookupError(
            f"Vispy has no visual contribution renderer for kind {kind!r} "
            f"and capability {capability!r}.{suffix}"
        ) from None


def create_visual_contribution_renderer(
    spec: Any,
    context: VisualContributionHostContext,
) -> Any:
    """Construct and validate one host-local contribution renderer."""
    if spec.capability != context.capability:
        raise LookupError(
            f"Panel {context.panel_id!r} exposes capability "
            f"{context.capability!r}, but visual contribution {spec.id!r} "
            f"requires {spec.capability!r}"
        )
    renderer = visual_contribution_renderer(
        spec.capability, spec.kind
    ).factory(context, spec)
    missing = [
        method
        for method in ("refresh", "clear")
        if not callable(getattr(renderer, method, None))
    ]
    if missing:
        raise TypeError(
            f"Visual contribution renderer for {spec.kind!r} is missing "
            f"required methods: {', '.join(missing)}"
        )
    return renderer


__all__ = [
    "PLOT_2D_LAYER_CAPABILITY",
    "SCENE_3D_LAYER_CAPABILITY",
    "VisualContributionRendererFactory",
    "VisualContributionRendererRegistration",
    "VisualContributionHostContext",
    "create_visual_contribution_renderer",
    "register_plot_contribution",
    "register_scene_contribution",
    "register_visual_contribution_renderer",
    "visual_contribution_renderer",
]
