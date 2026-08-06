"""Scene3D layer infrastructure and built-in discovery.

This module owns the *frontend-neutral* plumbing for 3-D views -- the refresh
context handed to every visual, and the visual registry -- and holds **no**
per-widget knowledge. Each 3-D widget's vispy implementation (``surface.py``,
``morphology.py``, …) self-registers its factory and *declares its ordered refresh
target kinds*; the frontend derives its dispatch/order tables from this registry, so
adding a 3-D widget touches only that widget's own module.

The built-in visuals are imported at the bottom purely to trigger their
self-registration; a third-party callback registers the same way and is loaded
deferred from an app-local import string or installed plugin metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Mapping

from compneurovis.core.app_spec import AppRef, app_ref

if TYPE_CHECKING:
    from compneurovis.core.app_spec import AppSpec
    from compneurovis.core.field import Field
    from compneurovis.frontends.vispy.view3d.viewport import Viewport3DVisual


@dataclass
class SceneLayerRefreshContext:
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


# --- Scene3D layer registry --------------------------------------------------
#
# A 3-D view renders as a *layer* in a shared canvas (alongside its operator overlays
# + axes), not a standalone host, so it registers here rather than in
# ``renderers.registry``. A visual declares the ordered refresh *target kinds* it
# renders (its sub-refreshes); the registry derives, for the frontend:
#   - which layer renders a given target kind (``scene_layer_for_target``),
#   - the global refresh order across visuals (``target_refresh_order``),
#   - the full set of scene target kinds (``scene_layer_target_kinds``).
# None of that lives in the frontend as a hardcoded table.

_SCENE_LAYER_FACTORIES: "dict[str, Callable[..., Viewport3DVisual]]" = {}
_SCENE_LAYER_TARGETS: dict[str, tuple[str, ...]] = {}
_SCENE_LAYER_REGISTRATIONS: dict[str, tuple[Any, ...]] = {}
_TARGET_TO_LAYER: dict[str, str] = {}
_TARGET_ORDER: dict[str, int] = {}
_SCENE_LAYER_TARGET_KINDS: frozenset[str] = frozenset()


def register_scene_layer(
    kind: str,
    factory: "Callable[..., Viewport3DVisual]",
    *,
    from_extension: Callable[[Any], Any],
    patch: dict[str, frozenset[str] | None],
    targets: "tuple[str, ...] | None" = None,
    value_binding: dict[str, frozenset[str]] | None = None,
    full_refresh: tuple[str, ...] | None = None,
    field_id_props: dict[str, str] | None = None,
    field_replace_hook: "Callable[..., set[Any]] | None" = None,
) -> None:
    """Register the complete Scene3D layer contract for one authored view kind.

    The config builder and patch schema are required so typed reconstruction and
    refresh behavior cannot be silently omitted. ``targets`` is the ordered tuple
    rendered by the visual and defaults to ``(kind,)``. Value-binding and field
    replacement routing are optional parts of the same registration.
    """
    key = str(kind).strip()
    if not key:
        raise ValueError("Scene layer kind cannot be empty")
    if not callable(factory):
        raise TypeError("Scene layer factory must be callable")
    if not callable(from_extension):
        raise TypeError("Scene layer from_extension builder must be callable")
    normalized_targets = tuple(targets) if targets else (key,)
    if len(set(normalized_targets)) != len(normalized_targets):
        raise ValueError(f"Scene layer {key!r} declares duplicate refresh targets")
    for target in normalized_targets:
        owner = _TARGET_TO_LAYER.get(target)
        if owner is not None and owner != key:
            raise ValueError(
                f"Scene refresh target {target!r} is already owned by {owner!r}"
            )
    registration = (
        factory,
        from_extension,
        normalized_targets,
        patch,
        value_binding,
        full_refresh or normalized_targets,
        field_id_props,
        field_replace_hook,
    )
    existing = _SCENE_LAYER_REGISTRATIONS.get(key)
    if existing is not None:
        if existing == registration:
            return
        raise ValueError(f"Scene layer {key!r} is already registered")
    _SCENE_LAYER_FACTORIES[key] = factory
    _SCENE_LAYER_TARGETS[key] = normalized_targets
    _SCENE_LAYER_REGISTRATIONS[key] = registration
    _rebuild_target_index()
    from compneurovis.frontends.vispy.refresh_planning import (
        register_view_refresh_schema,
    )
    from compneurovis.frontends.vispy.render_config import (
        register_view_render_config,
    )

    register_view_render_config(key, from_extension)
    register_view_refresh_schema(
        key,
        patch=patch,
        value_binding=value_binding,
        full_refresh=full_refresh or normalized_targets,
        field_id_props=field_id_props,
        field_replace_hook=field_replace_hook,
    )


def _rebuild_target_index() -> None:
    global _SCENE_LAYER_TARGET_KINDS
    _TARGET_TO_LAYER.clear()
    _TARGET_ORDER.clear()
    order = 0
    for layer_kind, target_kinds in _SCENE_LAYER_TARGETS.items():
        for target_kind in target_kinds:
            _TARGET_TO_LAYER[target_kind] = layer_kind
            _TARGET_ORDER[target_kind] = order
            order += 1
    _SCENE_LAYER_TARGET_KINDS = frozenset(_TARGET_TO_LAYER)


def scene_layer_for_target(target_kind: str) -> str | None:
    """The scene-layer kind that renders a refresh target, or None."""
    return _TARGET_TO_LAYER.get(target_kind)


def target_refresh_order(target_kind: str) -> int:
    """Global refresh order for a target kind (registration order across visuals)."""
    return _TARGET_ORDER.get(target_kind, 99)


def scene_layer_target_kinds() -> frozenset[str]:
    """All refresh target kinds rendered by registered Scene3D layers."""
    return _SCENE_LAYER_TARGET_KINDS


def create_scene_layers(
    view,
    *,
    kind: str,
    panel_id: str | None = None,
) -> "dict[str, Viewport3DVisual]":
    from compneurovis.frontends.vispy.plugins import (
        PLUGIN_ENTRY_POINT_GROUP,
        load_vispy_plugins,
    )

    load_vispy_plugins()
    factory = _SCENE_LAYER_FACTORIES.get(kind)
    if factory is None:
        raise LookupError(
            f"No Vispy Scene3D layer is installed for view kind {kind!r}. "
            f"Install a package exposing {PLUGIN_ENTRY_POINT_GROUP!r}."
        )
    visual = factory(view, panel_id=panel_id)
    required = ("refresh_for_target", "clear", "pick_entity")
    missing = [name for name in required if not callable(getattr(visual, name, None))]
    if missing:
        raise TypeError(
            f"Scene3D layer {kind!r} must implement {', '.join(required)}; "
            f"missing {', '.join(missing)}"
        )
    return {kind: visual}


# --- built-in 3-D visuals: importing them triggers self-registration ----------
# (Order matters only for the default refresh ordering across visuals.)
from compneurovis.frontends.vispy.view3d import morphology as _morphology  # noqa: E402,F401
from compneurovis.frontends.vispy.view3d import surface as _surface  # noqa: E402,F401
from compneurovis.frontends.vispy.view_inputs import grid_slice as _grid_slice  # noqa: E402,F401
