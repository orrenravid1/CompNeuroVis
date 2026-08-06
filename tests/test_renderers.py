"""Renderer registry contract.

Renderers register inside a frontend plugin callback. The registry stays strict
so it catches two different renderers claiming one kind, with an explicit
``override`` escape hatch for intentional replacement.
"""

from __future__ import annotations

import pytest

from compneurovis.frontends.vispy.panel_hosts import (
    require_vispy_panel_kind,
    require_vispy_view_3d_host_kind,
)
from compneurovis.frontends.vispy.renderers.registry import (
    _factories,
    register_renderer,
)


class _RendererA:
    def refresh(self, view, inputs, properties): ...  # pragma: no cover


class _RendererB:
    def refresh(self, view, inputs, properties): ...  # pragma: no cover


def test_reregistering_the_same_factory_is_idempotent():
    kind = "test_line_plot_clone"
    _factories.pop(kind, None)
    try:
        register_renderer(kind, _RendererA)
        register_renderer(kind, _RendererA)  # same object -> no-op
        assert _factories[kind] is _RendererA
    finally:
        _factories.pop(kind, None)


def test_a_different_renderer_claiming_a_taken_kind_raises():
    kind = "test_line_plot_clone"
    _factories.pop(kind, None)
    try:
        register_renderer(kind, _RendererA)
        with pytest.raises(ValueError, match="already registered"):
            register_renderer(kind, _RendererB)
    finally:
        _factories.pop(kind, None)


def test_override_replaces_intentionally():
    kind = "test_line_plot_clone"
    _factories.pop(kind, None)
    try:
        register_renderer(kind, _RendererA)
        register_renderer(kind, _RendererB, override=True)
        assert _factories[kind] is _RendererB
    finally:
        _factories.pop(kind, None)


def test_unknown_vispy_panel_kind_fails_with_supported_host_families():
    with pytest.raises(LookupError, match="standalone QWidget"):
        require_vispy_panel_kind("holographic")


def test_unknown_vispy_3d_host_kind_fails_as_a_shell_extension():
    with pytest.raises(LookupError, match="frontend-shell extension"):
        require_vispy_view_3d_host_kind("shared_scene")
