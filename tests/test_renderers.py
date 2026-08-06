"""Renderer registry contract.

Renderers register inside a frontend plugin callback. The registry stays strict
so it catches two different renderers claiming one kind, with an explicit
``override`` escape hatch for intentional replacement.
"""

from __future__ import annotations

import pytest

from compneurovis.frontends.vispy.panel_hosts import (
    _panel_host_factories,
    panel_host_factory,
    register_panel_host,
    registered_panel_kinds,
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


def test_panel_host_registration_is_collision_safe_and_dynamic():
    kind = "test_holographic_panel"

    def factory_a(context, panel):
        return None

    def factory_b(context, panel):
        return None

    _panel_host_factories.pop(kind, None)
    try:
        register_panel_host(kind, factory_a)
        register_panel_host(kind, factory_a)
        assert panel_host_factory(kind) is factory_a
        assert kind in registered_panel_kinds()
        with pytest.raises(ValueError, match="already registered"):
            register_panel_host(kind, factory_b)
        register_panel_host(kind, factory_b, override=True)
        assert panel_host_factory(kind) is factory_b
    finally:
        _panel_host_factories.pop(kind, None)


def test_unknown_panel_kind_requests_deferred_plugin_registration():
    with pytest.raises(LookupError, match="deferred Vispy plugin"):
        panel_host_factory("not_registered")
