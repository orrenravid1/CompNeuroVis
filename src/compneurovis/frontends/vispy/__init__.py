def __getattr__(name: str):
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
        "register_3d_visual",
        "register_view_refresh_schema",
        "register_view_render_config",
    ):
        from compneurovis.frontends.vispy.refresh_planning import (
            register_view_refresh_schema,
        )
        from compneurovis.frontends.vispy.render_config import (
            register_view_render_config,
        )
        from compneurovis.frontends.vispy.view3d.visuals import (
            load_vispy_plugins,
            register_3d_visual,
        )

        g = globals()
        g["load_vispy_plugins"] = load_vispy_plugins
        g["register_3d_visual"] = register_3d_visual
        g["register_view_refresh_schema"] = register_view_refresh_schema
        g["register_view_render_config"] = register_view_render_config
        return g[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "RenderHost",
    "VispyActorHost",
    "VispyFrontendWindow",
    "load_vispy_plugins",
    "register_3d_visual",
    "register_renderer",
    "register_view_refresh_schema",
    "register_view_render_config",
]
