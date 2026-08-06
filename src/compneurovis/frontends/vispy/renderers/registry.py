"""Renderer registry: maps a view ``kind`` to the Qt host that renders it.

Built-in and third-party views register here identically -- there is no separate
"extension" path, this is the one rendering path for every view kind.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol

from PyQt6 import QtWidgets

from compneurovis.core import AppRef, ExtensionViewSpec


class RenderHost(Protocol):
    """Qt host returned by a renderer factory."""

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


RenderHostFactory = Callable[..., QtWidgets.QWidget]
_factories: dict[str, RenderHostFactory] = {}


def register_renderer(
    kind: str, factory: RenderHostFactory, *, override: bool = False
) -> None:
    """Register one renderer factory under a stable view ``kind``.

    Call this inside a Vispy plugin callback. App-local authoring modules defer
    that callback with ``register_vispy_plugin("module:register")``; installed
    distributions expose the same callback through plugin metadata. The strict
    collision check catches two renderers claiming one kind. Pass
    ``override=True`` only for intentional replacement.
    """
    normalized = str(kind).strip()
    if not normalized:
        raise ValueError("Renderer kind cannot be empty")
    if not callable(factory):
        raise TypeError("Renderer factory must be callable")
    existing = _factories.get(normalized)
    if existing is not None and existing is not factory and not override:
        raise ValueError(
            f"Renderer {normalized!r} is already registered. Register renderers "
            f"inside one deferred frontend callback, or pass "
            f"override=True to replace it intentionally."
        )
    _factories[normalized] = factory


def create_host(
    view: ExtensionViewSpec,
    *,
    panel_id: str,
    view_id: str | AppRef,
    title: str,
) -> QtWidgets.QWidget:
    """Create the Qt host for one view via its registered renderer."""
    from compneurovis.frontends.vispy.plugins import load_vispy_plugins

    load_vispy_plugins()
    factory = _factories.get(view.kind)
    if factory is None:
        raise LookupError(
            f"No VisPy renderer is installed for view kind {view.kind!r}. "
            "Register an app-local callback with register_vispy_plugin(), or install "
            "a distribution exposing 'compneurovis.vispy_plugins'."
        )
    host = factory(panel_id=panel_id, view_id=view_id, title=title)
    if not isinstance(host, QtWidgets.QWidget) or not callable(getattr(host, "refresh", None)):
        raise TypeError(
            f"Renderer {view.kind!r} must return a QWidget with refresh(view, inputs, properties, values)"
        )
    return host


def _register_builtin_renderers() -> None:
    from compneurovis.frontends.vispy.panels.network2d import Network2DHostPanel
    from compneurovis.frontends.vispy.panels.plot_2d import (
        BarPlotHost,
        LinePlotHost,
    )

    register_renderer("network2d", Network2DHostPanel)
    register_renderer("line_plot", LinePlotHost)
    register_renderer("bar_plot", BarPlotHost)


_register_builtin_renderers()


__all__ = [
    "RenderHost",
    "RenderHostFactory",
    "create_host",
    "register_renderer",
]
