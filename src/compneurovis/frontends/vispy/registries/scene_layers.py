"""Scene3D layer infrastructure.

This module owns the *frontend-neutral* plumbing for 3-D views -- the refresh
context handed to every visual, and the visual registry -- and holds **no**
per-widget knowledge. Each 3-D widget's Vispy implementation (``surface.py``,
``morphology.py``, …) exposes a callback that registers its factory and *declares
its ordered refresh target kinds*; the frontend derives its dispatch/order tables
from this registry.

First-party and third-party component callbacks register through this same API.
First-party callbacks are invoked by the explicit built-in composition root.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
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
_SCENE_LAYER_REGISTRATIONS: dict[str, "_SceneLayerRegistration"] = {}
_TARGET_TO_LAYER: dict[str, str] = {}
_TARGET_ORDER: dict[str, int] = {}
_SCENE_LAYER_TARGET_KINDS: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class EntityPick:
    """Entity identity plus the authored click-interaction role."""

    interaction_role: str
    entity_id: str


@dataclass(frozen=True, slots=True)
class _SceneLayerRegistration:
    factory: "Callable[..., Viewport3DVisual]"
    from_view: Callable[[Any], Any]
    targets: tuple[str, ...]
    patch: Mapping[str, frozenset[str] | None]
    value_binding: Mapping[str, frozenset[str]] | None
    full_refresh: tuple[str, ...]
    field_id_props: Mapping[str, str] | None
    field_replace_hook: "Callable[..., set[Any]] | None"


def _target_name(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _target_schema(
    schema: Mapping[str, Any] | None,
    *,
    label: str,
    targets: frozenset[str],
    allow_none: bool,
) -> Mapping[str, Any] | None:
    if schema is None:
        return None
    if not isinstance(schema, Mapping):
        raise TypeError(f"{label} must be a mapping")
    copied: dict[str, Any] = {}
    for raw_target, raw_properties in schema.items():
        target = _target_name(raw_target, label=f"{label} target")
        if target not in targets:
            raise ValueError(
                f"{label} target {target!r} is not declared by the scene layer"
            )
        if target in copied:
            raise ValueError(f"{label} declares duplicate target {target!r}")
        if raw_properties is None:
            if not allow_none:
                raise TypeError(f"{label} target {target!r} requires properties")
            copied[target] = None
            continue
        if isinstance(raw_properties, str):
            raise TypeError(
                f"{label} properties for {target!r} must be an iterable of names"
            )
        properties: set[str] = set()
        for raw_property in raw_properties:
            property_name = _target_name(
                raw_property,
                label=f"{label} property",
            )
            properties.add(property_name)
        copied[target] = frozenset(properties)
    return MappingProxyType(copied)


def register_scene_layer(
    kind: str,
    factory: "Callable[..., Viewport3DVisual]",
    *,
    from_view: Callable[[Any], Any],
    patch: Mapping[str, frozenset[str] | None],
    targets: "tuple[str, ...] | None" = None,
    value_binding: Mapping[str, frozenset[str]] | None = None,
    full_refresh: tuple[str, ...] | None = None,
    field_id_props: Mapping[str, str] | None = None,
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
    if not callable(from_view):
        raise TypeError("Scene layer from_view builder must be callable")
    if field_replace_hook is not None and not callable(field_replace_hook):
        raise TypeError("Scene layer field_replace_hook must be callable")
    if field_id_props is not None and field_replace_hook is not None:
        raise ValueError(
            "Scene layers must use field_id_props or field_replace_hook, not both"
        )

    raw_targets = (key,) if targets is None else tuple(targets)
    if not raw_targets:
        raise ValueError(f"Scene layer {key!r} must declare at least one target")
    normalized_targets = tuple(
        _target_name(target, label="Scene refresh target")
        for target in raw_targets
    )
    if len(set(normalized_targets)) != len(normalized_targets):
        raise ValueError(f"Scene layer {key!r} declares duplicate refresh targets")
    target_set = frozenset(normalized_targets)

    from compneurovis.frontends.vispy.registries.renderers import (
        renderer_registered,
    )

    standalone_collisions = tuple(
        kind
        for kind in dict.fromkeys((key, *normalized_targets))
        if renderer_registered(kind)
    )
    if standalone_collisions:
        raise ValueError(
            "Scene3D layer kinds and refresh targets cannot also be standalone "
            f"renderer kinds: {standalone_collisions!r}"
        )

    normalized_patch = _target_schema(
        patch,
        label="Patch schema",
        targets=target_set,
        allow_none=True,
    )
    if normalized_patch is None:
        raise TypeError("Patch schema must be a mapping")
    normalized_value_binding = _target_schema(
        value_binding,
        label="Value-binding schema",
        targets=target_set,
        allow_none=False,
    )
    normalized_full_refresh = (
        normalized_targets
        if full_refresh is None
        else tuple(
            _target_name(target, label="Full-refresh target")
            for target in full_refresh
        )
    )
    if not normalized_full_refresh:
        raise ValueError(f"Scene layer {key!r} must refresh at least one target")
    unknown_full_refresh = set(normalized_full_refresh) - target_set
    if unknown_full_refresh:
        raise ValueError(
            f"Full-refresh targets {sorted(unknown_full_refresh)!r} are not "
            f"declared by scene layer {key!r}"
        )
    if len(set(normalized_full_refresh)) != len(normalized_full_refresh):
        raise ValueError(f"Scene layer {key!r} repeats a full-refresh target")

    normalized_field_id_props: Mapping[str, str] | None = None
    if field_id_props is not None:
        if not isinstance(field_id_props, Mapping):
            raise TypeError("field_id_props must be a mapping")
        copied_field_id_props: dict[str, str] = {}
        for raw_property, raw_target in field_id_props.items():
            property_name = _target_name(
                raw_property,
                label="Field-id property",
            )
            target = _target_name(raw_target, label="Field-id refresh target")
            if target not in target_set:
                raise ValueError(
                    f"Field-id refresh target {target!r} is not declared by "
                    f"scene layer {key!r}"
                )
            if property_name in copied_field_id_props:
                raise ValueError(
                    f"field_id_props repeats property {property_name!r}"
                )
            copied_field_id_props[property_name] = target
        normalized_field_id_props = MappingProxyType(copied_field_id_props)

    for target in normalized_targets:
        owner = _TARGET_TO_LAYER.get(target)
        if owner is not None and owner != key:
            raise ValueError(
                f"Scene refresh target {target!r} is already owned by {owner!r}"
            )
    registration = _SceneLayerRegistration(
        factory=factory,
        from_view=from_view,
        targets=normalized_targets,
        patch=normalized_patch,
        value_binding=normalized_value_binding,
        full_refresh=normalized_full_refresh,
        field_id_props=normalized_field_id_props,
        field_replace_hook=field_replace_hook,
    )
    existing = _SCENE_LAYER_REGISTRATIONS.get(key)
    if existing is not None and existing != registration:
        raise ValueError(f"Scene layer {key!r} is already registered")

    from compneurovis.frontends.vispy.refresh_planning import (
        _commit_view_refresh_schema_registration,
        _prepare_view_refresh_schema_registration,
        _validate_view_refresh_schema_registration,
    )
    from compneurovis.frontends.vispy.registries.render_configs import (
        _commit_view_render_config_registration,
        _validate_view_render_config_registration,
    )

    refresh_registration = _prepare_view_refresh_schema_registration(
        patch=normalized_patch,
        value_binding=normalized_value_binding,
        full_refresh=normalized_full_refresh,
        field_id_props=normalized_field_id_props,
        field_replace_hook=field_replace_hook,
    )
    _validate_view_render_config_registration(key, from_view)
    _validate_view_refresh_schema_registration(key, refresh_registration)

    # Every operation below is an assignment using preflighted immutable data.
    # No registry is changed until all collision and schema checks have passed.
    _commit_view_render_config_registration(key, from_view)
    _commit_view_refresh_schema_registration(key, refresh_registration)
    if existing is None:
        _SCENE_LAYER_FACTORIES[key] = factory
        _SCENE_LAYER_TARGETS[key] = normalized_targets
        _SCENE_LAYER_REGISTRATIONS[key] = registration
        _rebuild_target_index()


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


def scene_registry_claims_kind(kind: str) -> bool:
    """Whether Scene3D owns this name as a view kind or refresh target."""
    normalized = str(kind).strip()
    return (
        normalized in _SCENE_LAYER_REGISTRATIONS
        or normalized in _TARGET_TO_LAYER
    )


def target_refresh_order(target_kind: str) -> int:
    """Global refresh order for a target kind (registration order across visuals)."""
    return _TARGET_ORDER.get(target_kind, len(_TARGET_ORDER))


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
