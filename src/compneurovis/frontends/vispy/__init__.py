def __getattr__(name: str):
    if name in (
        "register_vispy_plugin",
        "PanelHostContext",
        "PanelHostLifecycle",
        "register_panel_host",
        "registered_panel_kinds",
    ):
        from compneurovis.frontends.vispy.plugins import register_vispy_plugin
        from compneurovis.frontends.vispy.registries.panel_hosts import (
            PanelHostContext,
            PanelHostLifecycle,
            register_panel_host,
            registered_panel_kinds,
        )

        globals()["register_vispy_plugin"] = register_vispy_plugin
        globals()["PanelHostContext"] = PanelHostContext
        globals()["PanelHostLifecycle"] = PanelHostLifecycle
        globals()["register_panel_host"] = register_panel_host
        globals()["registered_panel_kinds"] = registered_panel_kinds
        return globals()[name]
    if name in ("VispyActorHost", "VispyFrontendWindow"):
        from compneurovis.frontends.vispy.frontend import VispyFrontendWindow
        from compneurovis.frontends.vispy.host import VispyActorHost

        g = globals()
        g["VispyActorHost"] = VispyActorHost
        g["VispyFrontendWindow"] = VispyFrontendWindow
        return g[name]
    if name in ("register_renderer", "RenderHost"):
        from compneurovis.frontends.vispy.registries.renderers import (
            RenderHost,
            register_renderer,
        )

        g = globals()
        g["register_renderer"] = register_renderer
        g["RenderHost"] = RenderHost
        return g[name]
    if name in (
        "load_vispy_plugins",
        "SceneRenderLayer",
        "ControlRenderContext",
        "ResolvedControl",
        "OperatorResolveContext",
        "RefreshTarget",
        "register_scene_layer",
        "register_operator_adapter",
        "register_control_renderer",
        "register_scene_contribution",
        "register_plot_contribution",
        "VisualContributionHostContext",
        "VisualContributionRendererFactory",
        "create_visual_contribution_renderer",
        "register_visual_contribution_renderer",
    ):
        from compneurovis.frontends.vispy.registries.controls import (
            ControlRenderContext,
            ResolvedControl,
            register_control_renderer,
        )
        from compneurovis.frontends.vispy.registries.operators import (
            OperatorResolveContext,
            register_operator_adapter,
        )
        from compneurovis.frontends.vispy.plugins import (
            load_vispy_plugins,
        )
        from compneurovis.frontends.vispy.refresh_planning import RefreshTarget
        from compneurovis.frontends.vispy.rendering_policy import (
            SceneRenderLayer,
        )
        from compneurovis.frontends.vispy.registries.scene_layers import register_scene_layer
        from compneurovis.frontends.vispy.registries.visual_contributions import (
            VisualContributionHostContext,
            VisualContributionRendererFactory,
            create_visual_contribution_renderer,
            register_plot_contribution,
            register_scene_contribution,
            register_visual_contribution_renderer,
        )

        g = globals()
        g["load_vispy_plugins"] = load_vispy_plugins
        g["SceneRenderLayer"] = SceneRenderLayer
        g["ControlRenderContext"] = ControlRenderContext
        g["ResolvedControl"] = ResolvedControl
        g["OperatorResolveContext"] = OperatorResolveContext
        g["RefreshTarget"] = RefreshTarget
        g["register_scene_layer"] = register_scene_layer
        g["register_operator_adapter"] = register_operator_adapter
        g["register_control_renderer"] = register_control_renderer
        g["register_scene_contribution"] = register_scene_contribution
        g["register_plot_contribution"] = register_plot_contribution
        g["VisualContributionHostContext"] = VisualContributionHostContext
        g["VisualContributionRendererFactory"] = VisualContributionRendererFactory
        g["create_visual_contribution_renderer"] = create_visual_contribution_renderer
        g["register_visual_contribution_renderer"] = register_visual_contribution_renderer
        return g[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "RenderHost",
    "VispyActorHost",
    "VispyFrontendWindow",
    "PanelHostContext",
    "PanelHostLifecycle",
    "load_vispy_plugins",
    "SceneRenderLayer",
    "ControlRenderContext",
    "ResolvedControl",
    "OperatorResolveContext",
    "RefreshTarget",
    "register_scene_layer",
    "register_control_renderer",
    "register_scene_contribution",
    "register_plot_contribution",
    "VisualContributionHostContext",
    "VisualContributionRendererFactory",
    "create_visual_contribution_renderer",
    "register_visual_contribution_renderer",
    "register_operator_adapter",
    "register_panel_host",
    "register_renderer",
    "register_vispy_plugin",
    "registered_panel_kinds",
]
