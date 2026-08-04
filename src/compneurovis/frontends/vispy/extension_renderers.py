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
        values: Mapping[str, Any],
    ) -> None:
        """Refresh the visible widget from its current inputs.

        ``properties`` is the view's ``properties`` with runtime value bindings
        already resolved (convenient for simple renderers). ``values`` is the raw
        resolved-value table for this fragment; a renderer that needs to resolve
        bindings nested inside structured properties itself (e.g. reference-line
        markers, per-series styling) can read ``view.properties`` unresolved and
        resolve against ``values``.
        """


ExtensionHostFactory = Callable[..., QtWidgets.QWidget]
ENTRY_POINT_GROUP = "compneurovis.vispy_extensions"

_factories: dict[str, ExtensionHostFactory] = {}
_entry_points_loaded = False


def register_extension_renderer(
    kind: str, factory: ExtensionHostFactory, *, override: bool = False
) -> None:
    """Register one renderer factory under a stable extension-view kind.

    Register at *module import*, exactly as the built-in renderers do
    (:func:`_register_builtin_renderers`) -- never in an authoring script's top
    level. The actor architecture re-runs the script (``runpy`` in
    ``_script_actor_worker``), so a top-level registration would fire on every
    run and collide with itself; an imported module instead registers once per
    process (``sys.modules`` caches it, so re-runs re-import from cache). Keeping
    the check strict is what catches the real error this guards against: two
    different renderers claiming one kind. Pass ``override=True`` to replace a
    kind intentionally (hot reload, or shadowing a built-in).
    """
    normalized = str(kind).strip()
    if not normalized:
        raise ValueError("Extension renderer kind cannot be empty")
    if not callable(factory):
        raise TypeError("Extension renderer factory must be callable")
    existing = _factories.get(normalized)
    if existing is not None and existing is not factory and not override:
        raise ValueError(
            f"Extension renderer {normalized!r} is already registered. Register "
            f"renderers at module import (not in a re-run authoring script), or "
            f"pass override=True to replace it intentionally."
        )
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
    from compneurovis.frontends.vispy.panels.line_plot import (
        BarPlotExtensionHost,
        LinePlotExtensionHost,
    )

    register_extension_renderer("network2d", Network2DHostPanel)
    register_extension_renderer("line_plot", LinePlotExtensionHost)
    register_extension_renderer("bar_plot", BarPlotExtensionHost)


_register_builtin_renderers()


__all__ = [
    "ENTRY_POINT_GROUP",
    "ExtensionHost",
    "ExtensionHostFactory",
    "create_extension_host",
    "register_extension_renderer",
]
