# Register the built-in view/operator refresh contributions (light: pure data +
# spec logic, no vispy.scene). Importing any vispy-frontend submodule runs this,
# so the planner sees built-in surface/morphology/grid-slice on the same footing
# as a third-party kind -- no privileged registration path.
from compneurovis.frontends.vispy import refresh_registrations as _refresh_registrations  # noqa: E402,F401


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
