"""Shared 3-D visual infrastructure + built-in discovery.

This module owns the *frontend-neutral* plumbing for 3-D views -- the refresh
context handed to every visual, and the visual registry -- and holds **no**
per-widget knowledge. Each 3-D widget's vispy implementation (``surface.py``,
``morphology.py``, …) self-registers its factory and *declares its ordered refresh
target kinds*; the frontend derives its dispatch/order tables from this registry, so
adding a 3-D widget touches only that widget's own module.

The built-in visuals are imported at the bottom purely to trigger their
self-registration; a third-party 3-D visual registers the same way from its own
package and is loaded however that package is imported.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Any, Callable, Mapping

from compneurovis.core.app_spec import AppRef, app_ref

if TYPE_CHECKING:
    from compneurovis.core.app_spec import AppSpec
    from compneurovis.core.field import Field
    from compneurovis.frontends.vispy.view3d.viewport import Viewport3DVisual


@dataclass
class View3DRefreshContext:
    app_spec: "AppSpec"
    values: dict[str, Any]
    view_id: str | AppRef
    fields: "Mapping[AppRef, Field]" = field(default_factory=dict)
    active_layout: "Any" = None  # live LayoutSpec (AppProjection-resolved), not the blueprint default

    @property
    def fragment_id(self) -> str:
        return app_ref(self.view_id).fragment_id

    def field(self, field_id: str | AppRef | None):
        """Live materialized field value from AppProjection (never the blueprint)."""
        if not field_id:
            return None
        return self.fields.get(app_ref(field_id, fragment_id=self.fragment_id))


# --- 3-D visual registry -----------------------------------------------------
#
# A 3-D view renders as a *layer* in a shared canvas (alongside its operator overlays
# + axes), not a standalone host, so it registers here rather than in
# ``renderers.registry``. A visual declares the ordered refresh *target kinds* it
# renders (its sub-refreshes); the registry derives, for the frontend:
#   - which visual renders a given target kind (``visual_key_for_target``),
#   - the global refresh order across visuals (``target_refresh_order``),
#   - the full set of 3-D target kinds (``view_3d_target_kinds``).
# None of that lives in the frontend as a hardcoded table.

_3D_VISUAL_FACTORIES: "dict[str, Callable[..., Viewport3DVisual]]" = {}
_3D_VISUAL_TARGETS: dict[str, tuple[str, ...]] = {}
_TARGET_TO_VISUAL: dict[str, str] = {}
_TARGET_ORDER: dict[str, int] = {}
_VIEW_3D_TARGET_KINDS: frozenset[str] = frozenset()
PLUGIN_ENTRY_POINT_GROUP = "compneurovis.vispy_plugins"
_plugins_loaded = False


def register_3d_visual(
    kind: str,
    factory: "Callable[..., Viewport3DVisual]",
    *,
    targets: "tuple[str, ...] | None" = None,
) -> None:
    """Register a 3-D visual factory under a view ``kind`` (surface, morphology, …).

    ``targets`` is the ordered tuple of refresh target kinds this visual renders; it
    defaults to ``(kind,)`` for a single-target visual. A ``VIEW_3D`` panel mounts one
    visual per registered kind into its shared canvas; the panel's primary view
    activates the visual matching its ``kind``.
    """
    key = str(kind).strip()
    if not key:
        raise ValueError("3-D visual kind cannot be empty")
    if not callable(factory):
        raise TypeError("3-D visual factory must be callable")
    existing = _3D_VISUAL_FACTORIES.get(key)
    if existing is not None and existing is not factory:
        raise ValueError(f"3-D visual {key!r} is already registered")
    normalized_targets = tuple(targets) if targets else (key,)
    if len(set(normalized_targets)) != len(normalized_targets):
        raise ValueError(f"3-D visual {key!r} declares duplicate refresh targets")
    for target in normalized_targets:
        owner = _TARGET_TO_VISUAL.get(target)
        if owner is not None and owner != key:
            raise ValueError(
                f"3-D refresh target {target!r} is already owned by {owner!r}"
            )
    _3D_VISUAL_FACTORIES[key] = factory
    _3D_VISUAL_TARGETS[key] = normalized_targets
    _rebuild_target_index()


def _rebuild_target_index() -> None:
    global _VIEW_3D_TARGET_KINDS
    _TARGET_TO_VISUAL.clear()
    _TARGET_ORDER.clear()
    order = 0
    for visual_kind, target_kinds in _3D_VISUAL_TARGETS.items():
        for target_kind in target_kinds:
            _TARGET_TO_VISUAL[target_kind] = visual_kind
            _TARGET_ORDER[target_kind] = order
            order += 1
    _VIEW_3D_TARGET_KINDS = frozenset(_TARGET_TO_VISUAL)


def visual_key_for_target(target_kind: str) -> str | None:
    """The visual kind that renders a given refresh target kind (or None)."""
    return _TARGET_TO_VISUAL.get(target_kind)


def target_refresh_order(target_kind: str) -> int:
    """Global refresh order for a target kind (registration order across visuals)."""
    return _TARGET_ORDER.get(target_kind, 99)


def view_3d_target_kinds() -> frozenset[str]:
    """All refresh target kinds any registered 3-D visual renders."""
    return _VIEW_3D_TARGET_KINDS


def load_vispy_plugins() -> None:
    """Load installed frontend contributions in the frontend process."""
    global _plugins_loaded
    if _plugins_loaded:
        return
    _plugins_loaded = True
    discovered = entry_points()
    selected = (
        discovered.select(group=PLUGIN_ENTRY_POINT_GROUP)
        if hasattr(discovered, "select")
        else discovered.get(PLUGIN_ENTRY_POINT_GROUP, ())
    )
    for entry_point in selected:
        register = entry_point.load()
        if not callable(register):
            raise TypeError(
                f"Vispy plugin entry point {entry_point.name!r} must be callable"
            )
        register()


def create_3d_visuals(
    view,
    *,
    kind: str,
    panel_id: str | None = None,
) -> "dict[str, Viewport3DVisual]":
    load_vispy_plugins()
    factory = _3D_VISUAL_FACTORIES.get(kind)
    if factory is None:
        raise LookupError(
            f"No Vispy 3-D visual is installed for view kind {kind!r}. "
            f"Install a package exposing {PLUGIN_ENTRY_POINT_GROUP!r}."
        )
    return {kind: factory(view, panel_id=panel_id)}


# --- built-in 3-D visuals: importing them triggers self-registration ----------
# (Order matters only for the default refresh ordering across visuals.)
from compneurovis.frontends.vispy.view3d import morphology as _morphology  # noqa: E402,F401
from compneurovis.frontends.vispy.view3d import surface as _surface  # noqa: E402,F401
