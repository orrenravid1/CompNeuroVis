"""Renderer registry for source-authored extension views."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from importlib.metadata import entry_points
from typing import Any, Protocol

from PyQt6 import QtWidgets

from compneurovis.core import AppRef, ExtensionViewSpec


class ExtensionHost(Protocol):
    """Qt host returned by an extension renderer factory."""

    def refresh(
        self,
        view: ExtensionViewSpec,
        inputs: Mapping[str, Any],
        properties: Mapping[str, Any],
    ) -> None:
        """Refresh the visible widget from its current inputs."""


ExtensionHostFactory = Callable[..., QtWidgets.QWidget]
ENTRY_POINT_GROUP = "compneurovis.vispy_extensions"

_factories: dict[str, ExtensionHostFactory] = {}
_entry_points_loaded = False


def register_extension_renderer(kind: str, factory: ExtensionHostFactory) -> None:
    """Register one renderer factory under a stable extension-view kind."""
    normalized = str(kind).strip()
    if not normalized:
        raise ValueError("Extension renderer kind cannot be empty")
    if not callable(factory):
        raise TypeError("Extension renderer factory must be callable")
    existing = _factories.get(normalized)
    if existing is not None and existing is not factory:
        raise ValueError(f"Extension renderer {normalized!r} is already registered")
    _factories[normalized] = factory


def create_extension_host(
    view: ExtensionViewSpec,
    *,
    panel_id: str,
    view_id: str | AppRef,
    title: str,
) -> QtWidgets.QWidget:
    """Create the Qt host for one extension view."""
    _load_entry_point_renderers()
    factory = _factories.get(view.kind)
    if factory is None:
        raise LookupError(
            f"No VisPy renderer is installed for extension view {view.kind!r}. "
            f"Install a package exposing the {ENTRY_POINT_GROUP!r} entry-point group."
        )
    host = factory(panel_id=panel_id, view_id=view_id, title=title)
    if not isinstance(host, QtWidgets.QWidget) or not callable(getattr(host, "refresh", None)):
        raise TypeError(
            f"Renderer {view.kind!r} must return a QWidget with refresh(view, inputs, properties)"
        )
    return host


def _load_entry_point_renderers() -> None:
    global _entry_points_loaded
    if _entry_points_loaded:
        return
    _entry_points_loaded = True
    discovered = entry_points()
    selected = (
        discovered.select(group=ENTRY_POINT_GROUP)
        if hasattr(discovered, "select")
        else discovered.get(ENTRY_POINT_GROUP, ())
    )
    for entry_point in selected:
        register_extension_renderer(entry_point.name, entry_point.load())


def _register_builtin_renderers() -> None:
    from compneurovis.frontends.vispy.panels.network2d import Network2DHostPanel

    register_extension_renderer("network2d", Network2DHostPanel)


_register_builtin_renderers()


__all__ = [
    "ENTRY_POINT_GROUP",
    "ExtensionHost",
    "ExtensionHostFactory",
    "create_extension_host",
    "register_extension_renderer",
]
