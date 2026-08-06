def __getattr__(name: str):
    if name in (
        "register_vispy_plugin",
        "PanelHostContext",
        "PanelHostLifecycle",
        "register_panel_host",
        "registered_panel_kinds",
    ):
        from compneurovis.frontends.vispy.plugins import register_vispy_plugin
        from compneurovis.frontends.vispy.panel_hosts import (
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
        from compneurovis.frontends.vispy.renderers.registry import (
            RenderHost,
            register_renderer,
        )

        g = globals()
        g["register_renderer"] = register_renderer
        g["RenderHost"] = RenderHost
        return g[name]
    if name in (
        "load_vispy_plugins",
        "OperatorResolveContext",
        "RefreshTarget",
        "register_scene_layer",
        "register_operator_adapter",
        "register_control_renderer",
        "register_action_renderer",
        "register_scene_contribution",
        "register_plot_contribution",
    ):
        from compneurovis.frontends.vispy.control_renderers import (
            register_action_renderer,
            register_control_renderer,
        )
        from compneurovis.frontends.vispy.operator_adapters import (
            OperatorResolveContext,
            register_operator_adapter,
        )
        from compneurovis.frontends.vispy.plugins import (
            load_vispy_plugins,
        )
        from compneurovis.frontends.vispy.refresh_planning import RefreshTarget
        from compneurovis.frontends.vispy.view3d.visuals import (
            register_scene_layer,
        )
        from compneurovis.frontends.vispy.visual_contributions import (
            register_plot_contribution,
            register_scene_contribution,
        )

        g = globals()
        g["load_vispy_plugins"] = load_vispy_plugins
        g["OperatorResolveContext"] = OperatorResolveContext
        g["RefreshTarget"] = RefreshTarget
        g["register_scene_layer"] = register_scene_layer
        g["register_operator_adapter"] = register_operator_adapter
        g["register_control_renderer"] = register_control_renderer
        g["register_action_renderer"] = register_action_renderer
        g["register_scene_contribution"] = register_scene_contribution
        g["register_plot_contribution"] = register_plot_contribution
        return g[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "RenderHost",
    "VispyActorHost",
    "VispyFrontendWindow",
    "PanelHostContext",
    "PanelHostLifecycle",
    "load_vispy_plugins",
    "OperatorResolveContext",
    "RefreshTarget",
    "register_scene_layer",
    "register_control_renderer",
    "register_action_renderer",
    "register_scene_contribution",
    "register_plot_contribution",
    "register_operator_adapter",
    "register_panel_host",
    "register_renderer",
    "register_vispy_plugin",
    "registered_panel_kinds",
]
