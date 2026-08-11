"""Experimental generic notebook frontend and presentation contracts.

Exports are lazy so registry and RunSpec users do not import Qt/Vispy merely by
importing this package.
"""

from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "NotebookFrontend": (".frontend", "NotebookFrontend"),
    "NotebookActorHost": (".host", "NotebookActorHost"),
    "NotebookRuntimeOptions": (".runtime", "NotebookRuntimeOptions"),
    "NotebookActionRenderContext": (
        ".registries",
        "NotebookActionRenderContext",
    ),
    "NotebookControlPresentation": (
        ".registries",
        "NotebookControlPresentation",
    ),
    "NotebookControlRenderContext": (
        ".registries",
        "NotebookControlRenderContext",
    ),
    "NotebookFramePolicy": (".registries", "NotebookFramePolicy"),
    "register_action_renderer": (".registries", "register_action_renderer"),
    "register_control_renderer": (".registries", "register_control_renderer"),
    "register_frame_policy": (".registries", "register_frame_policy"),
}


def __getattr__(name: str):
    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from exc
    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted((*globals(), *_EXPORTS))

__all__ = [
    *_EXPORTS,
]
