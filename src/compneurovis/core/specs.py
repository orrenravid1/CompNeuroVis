from __future__ import annotations

from dataclasses import dataclass


class SpecBase:
    """Marker for immutable declarative blueprint values."""


@dataclass(frozen=True, slots=True)
class IdentifiedSpec(SpecBase):
    """Base for immutable specs addressed by a stable id."""

    id: str


# Panel kinds — the frontend panel category a view declares itself for. Defined
# here (not in app_spec) so views.py can import them without an import cycle, and
# so a view's declared kind is validated uniformly rather than by isinstance.
PANEL_KIND_VIEW_3D = "view_3d"
PANEL_KIND_LINE_PLOT = "line_plot"
PANEL_KIND_BAR_PLOT = "bar_plot"
PANEL_KIND_CONTROLS = "controls"
PANEL_KIND_EXTENSION = "extension"


__all__ = [
    "IdentifiedSpec",
    "SpecBase",
    "PANEL_KIND_VIEW_3D",
    "PANEL_KIND_LINE_PLOT",
    "PANEL_KIND_BAR_PLOT",
    "PANEL_KIND_CONTROLS",
    "PANEL_KIND_EXTENSION",
]
