"""Extension-renderer registry contract.

Renderers register at *module import* (like the built-ins in
``_register_builtin_renderers``), never in an authoring script's top level: the
actor architecture re-runs the script (``runpy`` in ``_script_actor_worker``),
and ``sys.modules`` caching makes an imported registration fire once per process.
Given that, the registry stays strict -- so it still catches the real error, two
different renderers claiming one kind -- with an explicit ``override`` escape
hatch for intentional replacement (hot reload, shadowing a built-in).
"""

from __future__ import annotations

import pytest

from compneurovis.frontends.vispy.extension_renderers import (
    _factories,
    register_extension_renderer,
)


class _RendererA:
    def refresh(self, view, inputs, properties): ...  # pragma: no cover


class _RendererB:
    def refresh(self, view, inputs, properties): ...  # pragma: no cover


def test_reregistering_the_same_factory_is_idempotent():
    kind = "test_line_plot_clone"
    _factories.pop(kind, None)
    try:
        register_extension_renderer(kind, _RendererA)
        register_extension_renderer(kind, _RendererA)  # same object -> no-op
        assert _factories[kind] is _RendererA
    finally:
        _factories.pop(kind, None)


def test_a_different_renderer_claiming_a_taken_kind_raises():
    kind = "test_line_plot_clone"
    _factories.pop(kind, None)
    try:
        register_extension_renderer(kind, _RendererA)
        with pytest.raises(ValueError, match="already registered"):
            register_extension_renderer(kind, _RendererB)
    finally:
        _factories.pop(kind, None)


def test_override_replaces_intentionally():
    kind = "test_line_plot_clone"
    _factories.pop(kind, None)
    try:
        register_extension_renderer(kind, _RendererA)
        register_extension_renderer(kind, _RendererB, override=True)
        assert _factories[kind] is _RendererB
    finally:
        _factories.pop(kind, None)
