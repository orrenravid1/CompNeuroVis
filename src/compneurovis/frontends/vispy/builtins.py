"""Explicit composition root for first-party Vispy capabilities."""

from __future__ import annotations

from compneurovis.core.app_spec import PANEL_KIND_EXTENSION

_registered = False


def register_first_party_vispy() -> None:
    """Register every Vispy capability shipped in the CompNeuroVis wheel."""
    global _registered
    if _registered:
        return

    # Component imports register scene layers, operators, and contributions through
    # the same public APIs used by third-party components.
    from compneurovis.components.grid_slice import vispy as grid_slice
    from compneurovis.components.level_marker import vispy as level_marker
    from compneurovis.components.morphology import vispy as morphology
    from compneurovis.components.surface import vispy as surface
    from compneurovis.components.network2d.vispy import Network2DHostPanel
    from compneurovis.components.line.vispy import LinePlotHost
    from compneurovis.components.bar.vispy import BarPlotHost
    from compneurovis.frontends.vispy.hosts import (
        ControlsPanelLifecycle,
        ExtensionPanelLifecycle,
        Scene3DPanelLifecycle,
    )
    from compneurovis.frontends.vispy.controls.renderers import (
        register_first_party_control_renderers,
    )
    from compneurovis.frontends.vispy.registries.panel_hosts import register_panel_host
    from compneurovis.frontends.vispy.registries.renderers import register_renderer

    register_renderer("network2d", Network2DHostPanel)
    register_renderer("line_plot", LinePlotHost)
    register_renderer("bar_plot", BarPlotHost)
    register_panel_host("controls", ControlsPanelLifecycle)
    register_panel_host(PANEL_KIND_EXTENSION, ExtensionPanelLifecycle)
    register_panel_host("scene_3d", Scene3DPanelLifecycle)
    register_first_party_control_renderers()
    _registered = True

    del grid_slice, level_marker, morphology, surface


__all__ = ["register_first_party_vispy"]
