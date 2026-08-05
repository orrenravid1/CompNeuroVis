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
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["VispyActorHost", "VispyFrontendWindow", "register_renderer", "RenderHost"]
