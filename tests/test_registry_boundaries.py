from __future__ import annotations

import subprocess
import sys
import textwrap


def test_first_party_composition_roots_are_explicit_and_complete():
    """Inline authoring bootstraps once; VisPy stays neutral until its root runs."""
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

        # Importing a VisPy component implementation only defines it. Frontend
        # registration is owned by the explicit composition root below. Inline
        # authoring already ran its own root while importing the public package.
        import compneurovis.components.grid_slice.vispy
        import compneurovis.components.level_marker.vispy
        import compneurovis.components.morphology.vispy
        import compneurovis.components.surface.vispy

        assert set(widget_registry._widget_factories) == {
            "line",
            "bar",
            "network2d",
            "morphology",
            "surface",
            "grid_slice",
            "level_marker",
        }
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


def test_importing_desktop_frontend_does_not_select_a_vispy_backend():
    script = textwrap.dedent(
        """
        from vispy import config
        from vispy.app import _default_app

        gl_backend = config["gl_backend"]
        assert _default_app.default_app is None

        import compneurovis.frontends.vispy.frontend

        assert _default_app.default_app is None
        assert config["gl_backend"] == gl_backend
        """
    )
    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )


def test_vispy_view_kind_has_one_unambiguous_host_ownership_model():
    script = textwrap.dedent(
        """
        from compneurovis.frontends.vispy import (
            VisualContributionHostContext,
            create_visual_contribution_renderer,
            register_renderer,
            register_scene_layer,
            register_visual_contribution_renderer,
        )

        assert VisualContributionHostContext is not None
        assert callable(create_visual_contribution_renderer)
        assert callable(register_visual_contribution_renderer)

        register_renderer("ambiguous_standalone", lambda **kwargs: None)
        try:
            register_scene_layer(
                "ambiguous_standalone",
                lambda **kwargs: None,
                from_view=lambda view: view,
                patch={"ambiguous_standalone": None},
            )
        except ValueError as exc:
            assert "standalone renderer kinds" in str(exc)
        else:
            raise AssertionError("Scene3D accepted a standalone view kind")

        register_scene_layer(
            "ambiguous_scene",
            lambda **kwargs: None,
            from_view=lambda view: view,
            patch={"ambiguous_scene": None},
        )
        try:
            register_renderer("ambiguous_scene", lambda **kwargs: None)
        except ValueError as exc:
            assert "already owned by a Scene3D" in str(exc)
        else:
            raise AssertionError("standalone accepted a Scene3D view kind")
        """
    )
    subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
