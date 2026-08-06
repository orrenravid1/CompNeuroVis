from __future__ import annotations

import subprocess
import sys
import textwrap


def test_public_registries_do_not_bootstrap_first_party_implementations():
    """Registry imports stay neutral; the named first-party bootstrap is explicit."""
    script = textwrap.dedent(
        """
        from compneurovis.inline import widget_registry
        from compneurovis.frontends.vispy.registries import renderers as registry
        from compneurovis.frontends.vispy.registries import scene_layers as visuals

        assert not widget_registry._widget_factories
        assert not registry._factories
        assert not visuals._SCENE_LAYER_FACTORIES

        from compneurovis.frontends.vispy.builtins import register_first_party_vispy

        register_first_party_vispy()
        assert set(registry._factories) == {"network2d", "line_plot", "bar_plot"}
        assert set(visuals._SCENE_LAYER_FACTORIES) == {"morphology", "surface"}
        """
    )
    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
