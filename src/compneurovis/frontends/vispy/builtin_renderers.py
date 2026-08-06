"""Explicit bootstrap for the renderers shipped with CompNeuroVis."""

from __future__ import annotations


_registered = False


def register_builtin_renderers() -> None:
    """Register first-party view, scene-layer, operator, and contribution renderers."""
    global _registered
    if _registered:
        return

    # These first-party component modules self-register through the same public
    # APIs available to third parties. Imports belong here, never in a registry.
    from compneurovis.frontends.vispy.view_inputs import grid_slice, level_marker
    from compneurovis.frontends.vispy.view3d import morphology, surface
    from compneurovis.frontends.vispy.panels.network2d import Network2DHostPanel
    from compneurovis.frontends.vispy.panels.plot_2d import (
        BarPlotHost,
        LinePlotHost,
    )
    from compneurovis.frontends.vispy.renderers.registry import register_renderer

    register_renderer("network2d", Network2DHostPanel)
    register_renderer("line_plot", LinePlotHost)
    register_renderer("bar_plot", BarPlotHost)
    _registered = True

    # Make the side-effect-only component imports explicit to readers and lint.
    del grid_slice, level_marker, morphology, surface


__all__ = ["register_builtin_renderers"]
