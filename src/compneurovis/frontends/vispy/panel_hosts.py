"""Panel-host families implemented by the Vispy frontend."""

from __future__ import annotations

from compneurovis.core.app_spec import (
    PANEL_KIND_CONTROLS,
    PANEL_KIND_EXTENSION,
    PANEL_KIND_VIEW_3D,
)

VISPY_PANEL_KINDS = (
    PANEL_KIND_EXTENSION,
    PANEL_KIND_VIEW_3D,
    PANEL_KIND_CONTROLS,
)
VISPY_VIEW_3D_HOST_KINDS = ("independent_canvas",)


def require_vispy_panel_kind(kind: str) -> None:
    """Reject a neutral panel kind for which Vispy has no host lifecycle."""
    if kind not in VISPY_PANEL_KINDS:
        supported = ", ".join(repr(item) for item in VISPY_PANEL_KINDS)
        raise LookupError(
            f"Vispy does not implement panel kind {kind!r}. Supported panel-host "
            f"families are {supported}. Use an 'extension' panel for any standalone "
            "QWidget (including 2-D plots, tables, images, text, and custom UI), "
            "or implement a separate frontend/shell extension for a new host family."
        )


def require_vispy_view_3d_host_kind(kind: str) -> None:
    """Reject an unsupported shared-canvas ownership/lifecycle strategy."""
    if kind not in VISPY_VIEW_3D_HOST_KINDS:
        raise LookupError(
            f"Vispy does not implement 3-D host kind {kind!r}. The supported host "
            "kind is 'independent_canvas'. A new canvas/shell lifecycle requires "
            "a frontend-shell extension, not an ordinary widget registration."
        )


__all__ = [
    "VISPY_PANEL_KINDS",
    "VISPY_VIEW_3D_HOST_KINDS",
    "require_vispy_panel_kind",
    "require_vispy_view_3d_host_kind",
]
