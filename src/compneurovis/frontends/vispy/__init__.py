def __getattr__(name: str):
    if name in (
        "register_vispy_plugin",
        "VISPY_PANEL_KINDS",
        "VISPY_VIEW_3D_HOST_KINDS",
    ):
        from compneurovis.frontends.vispy.plugins import register_vispy_plugin
        from compneurovis.frontends.vispy.panel_hosts import (
            VISPY_PANEL_KINDS,
            VISPY_VIEW_3D_HOST_KINDS,
        )

        globals()["register_vispy_plugin"] = register_vispy_plugin
        globals()["VISPY_PANEL_KINDS"] = VISPY_PANEL_KINDS
        globals()["VISPY_VIEW_3D_HOST_KINDS"] = VISPY_VIEW_3D_HOST_KINDS
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
        "register_3d_visual",
        "register_operator_adapter",
    ):
        from compneurovis.frontends.vispy.operator_adapters import (
            OperatorResolveContext,
            register_operator_adapter,
        )
        from compneurovis.frontends.vispy.plugins import (
            load_vispy_plugins,
        )
        from compneurovis.frontends.vispy.refresh_planning import RefreshTarget
        from compneurovis.frontends.vispy.view3d.visuals import (
            register_3d_visual,
        )

        g = globals()
        g["load_vispy_plugins"] = load_vispy_plugins
        g["OperatorResolveContext"] = OperatorResolveContext
        g["RefreshTarget"] = RefreshTarget
        g["register_3d_visual"] = register_3d_visual
        g["register_operator_adapter"] = register_operator_adapter
        return g[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "RenderHost",
    "VispyActorHost",
    "VispyFrontendWindow",
    "VISPY_PANEL_KINDS",
    "VISPY_VIEW_3D_HOST_KINDS",
    "load_vispy_plugins",
    "OperatorResolveContext",
    "RefreshTarget",
    "register_3d_visual",
    "register_operator_adapter",
    "register_renderer",
    "register_vispy_plugin",
]
