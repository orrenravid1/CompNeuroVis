from compneurovis.frontends.base import FrontendBase


def __getattr__(name: str):
    if name in ("VispyActorHost", "VispyFrontendWindow"):
        from compneurovis.frontends.vispy import VispyActorHost, VispyFrontendWindow
        g = globals()
        g["VispyActorHost"] = VispyActorHost
        g["VispyFrontendWindow"] = VispyFrontendWindow
        return g[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["FrontendBase", "VispyActorHost", "VispyFrontendWindow"]
