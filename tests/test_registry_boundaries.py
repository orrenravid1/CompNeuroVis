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
        from compneurovis.frontends.vispy.registries import controls
        from compneurovis.frontends.vispy.registries import operators
        from compneurovis.frontends.vispy.registries import panel_hosts
        from compneurovis.frontends.vispy.registries import render_configs
        from compneurovis.frontends.vispy.registries import visual_contributions

        # Importing a component implementation only defines it. Registration is
        # owned by the explicit first-party composition root below.
        import compneurovis.components.grid_slice.vispy
        import compneurovis.components.level_marker.vispy
        import compneurovis.components.morphology.vispy
        import compneurovis.components.surface.vispy

        assert not widget_registry._widget_factories
        assert not registry._factories
        assert not visuals._SCENE_LAYER_FACTORIES
        assert not controls._control_renderers
        assert not controls._action_renderers
        assert not operators._OPERATOR_ADAPTERS
        assert not panel_hosts._panel_host_factories
        assert not render_configs._VIEW_RENDER_CONFIGS
        assert not visual_contributions._renderers

        from compneurovis.frontends.vispy.builtins import register_first_party_vispy

        register_first_party_vispy()
        register_first_party_vispy()
        assert set(registry._factories) == {"network2d", "line_plot", "bar_plot"}
        assert set(visuals._SCENE_LAYER_FACTORIES) == {"morphology", "surface"}
        assert set(render_configs._VIEW_RENDER_CONFIGS) == {"morphology", "surface"}
        assert set(operators._OPERATOR_ADAPTERS) == {"grid_slice"}
        assert set(panel_hosts._panel_host_factories) == {
            "controls", "standalone", "scene_3d"
        }
        assert set(controls._control_renderers) == {
            "slider", "spinbox", "checkbox", "dropdown", "text", "xy_pad"
        }
        assert set(controls._action_renderers) == {"button"}
        assert set(visual_contributions._renderers) == {
            (visual_contributions.SCENE_3D_LAYER_CAPABILITY, "grid_slice_overlay"),
            (visual_contributions.PLOT_2D_LAYER_CAPABILITY, "level_marker"),
        }
        """
    )
    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
