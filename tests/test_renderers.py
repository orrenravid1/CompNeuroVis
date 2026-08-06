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
from compneurovis.frontends.vispy.control_renderers import (
    _action_renderers,
    _control_renderers,
    action_renderer,
    control_renderer,
    register_action_renderer,
    register_control_renderer,
)
from compneurovis.frontends.vispy.visual_contributions import (
    PLOT_2D_LAYER_CAPABILITY,
    SCENE_3D_LAYER_CAPABILITY,
    _renderers as _visual_contribution_renderers,
    register_plot_contribution,
    register_scene_contribution,
    visual_contribution_renderer,
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


def test_control_and_action_renderer_registries_are_open_and_collision_safe():
    control_kind = "test_knob"
    action_kind = "test_split_button"

    def control_a(panel, spec, value):
        return ("a", value)

    def control_b(panel, spec, value):
        return ("b", value)

    def action_a(panel, spec, values):
        return ("action", values)

    _control_renderers.pop(control_kind, None)
    _action_renderers.pop(action_kind, None)
    try:
        register_control_renderer(control_kind, control_a, full_width=True)
        register_control_renderer(control_kind, control_a, full_width=True)
        registration = control_renderer(control_kind)
        assert registration.factory is control_a
        assert registration.full_width
        with pytest.raises(ValueError, match="already registered"):
            register_control_renderer(control_kind, control_b)
        register_control_renderer(control_kind, control_b, override=True)
        assert control_renderer(control_kind).factory is control_b

        register_action_renderer(action_kind, action_a)
        assert action_renderer(action_kind).factory is action_a
        with pytest.raises(ValueError, match="already registered"):
            register_action_renderer(action_kind, control_a)
    finally:
        _control_renderers.pop(control_kind, None)
        _action_renderers.pop(action_kind, None)


def test_visual_contribution_kinds_are_scoped_by_target_capability():
    kind = "test_halo"

    def scene_factory(*args):
        return ("scene", args)

    def plot_factory(*args):
        return ("plot", args)

    scene_key = (SCENE_3D_LAYER_CAPABILITY, kind)
    plot_key = (PLOT_2D_LAYER_CAPABILITY, kind)
    _visual_contribution_renderers.pop(scene_key, None)
    _visual_contribution_renderers.pop(plot_key, None)
    try:
        register_scene_contribution(kind, scene_factory)
        register_plot_contribution(kind, plot_factory)
        assert (
            visual_contribution_renderer(*scene_key).factory is scene_factory
        )
        assert visual_contribution_renderer(*plot_key).factory is plot_factory
        with pytest.raises(ValueError, match="already registered"):
            register_scene_contribution(kind, plot_factory)
        with pytest.raises(LookupError, match="no visual contribution renderer"):
            visual_contribution_renderer(
                SCENE_3D_LAYER_CAPABILITY, "not_registered"
            )
    finally:
        _visual_contribution_renderers.pop(scene_key, None)
        _visual_contribution_renderers.pop(plot_key, None)
