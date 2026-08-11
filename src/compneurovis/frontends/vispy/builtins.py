"""Explicit composition root for first-party Vispy capabilities."""

from __future__ import annotations

from compneurovis.core.app_spec import PANEL_KIND_STANDALONE

_registered = False


def register_first_party_vispy() -> None:
    """Register every Vispy capability shipped in the CompNeuroVis wheel."""
    global _registered
    if _registered:
        return

    from compneurovis.components.network2d.vispy import Network2DHostPanel
    from compneurovis.components.line.vispy import LinePlotHost
    from compneurovis.components.bar.vispy import BarPlotHost
    from compneurovis.components.grid_slice.vispy import register_grid_slice_vispy
    from compneurovis.components.level_marker.vispy import (
        register_level_marker_vispy,
    )
    from compneurovis.components.morphology.vispy import register_morphology_vispy
    from compneurovis.components.surface.vispy import register_surface_vispy
    from compneurovis.frontends.vispy.hosts import (
        ControlsPanelLifecycle,
        StandalonePanelLifecycle,
        Scene3DPanelLifecycle,
    )
    from compneurovis.frontends.vispy.controls.renderers import (
        register_first_party_control_renderers,
    )
    from compneurovis.frontends.vispy.registries.panel_hosts import register_panel_host
    from compneurovis.frontends.vispy.registries.renderers import register_renderer
    from compneurovis.frontends.vispy.notebook.registries import (
        register_frame_policy,
    )

    # Panel lifecycles.
    register_panel_host("controls", ControlsPanelLifecycle)
    register_panel_host(PANEL_KIND_STANDALONE, StandalonePanelLifecycle)
    register_panel_host("scene_3d", Scene3DPanelLifecycle)

    # Standalone view renderers.
    register_renderer("network2d", Network2DHostPanel)
    register_renderer("line_plot", LinePlotHost)
    register_renderer("bar_plot", BarPlotHost)

    # Notebook raster service levels. These are ordinary view-kind
    # registrations; third-party renderers use the same API.
    register_frame_policy(
        "morphology", target_hz=30.0, priority=100, max_inflight=3
    )
    register_frame_policy("surface", target_hz=10.0, priority=70)
    register_frame_policy("network2d", target_hz=10.0, priority=60)
    register_frame_policy("line_plot", target_hz=4.0, priority=20)
    register_frame_policy("bar_plot", target_hz=4.0, priority=20)

    # Shared-scene layers, derived data, and owner-authored contributions.
    register_morphology_vispy()
    register_surface_vispy()
    register_grid_slice_vispy()
    register_level_marker_vispy()

    # Typed control and action presentation.
    register_first_party_control_renderers()
    _registered = True


__all__ = ["register_first_party_vispy"]
