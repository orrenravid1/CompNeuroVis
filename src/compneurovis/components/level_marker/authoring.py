"""Independently authored level-marker contribution for Plot2D panels."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from compneurovis.inline.refs import PanelRef
from compneurovis.inline.widgets.api import Widget

if TYPE_CHECKING:
    from compneurovis.inline.widgets.api import WidgetAuthoringContext


@dataclass(frozen=True, slots=True)
class LevelMarker(Widget[PanelRef]):
    """Plot2D contribution owned by the marker rather than its target plot."""

    target: PanelRef
    value: Any
    orientation: str = "horizontal"
    color: Any = "#d62728"
    width: float = 2.0
    label: str = ""

    def declare(self, context: "WidgetAuthoringContext") -> PanelRef:
        orientation = str(self.orientation).strip().lower()
        if orientation not in {"horizontal", "vertical"}:
            raise ValueError(
                "LevelMarker orientation must be 'horizontal' or 'vertical'"
            )
        context.visual_contribution(
            "level_marker",
            "level",
            target=self.target,
            capability="plot2d.layers/v1",
            properties={
                "value": self.value,
                "orientation": orientation,
                "color": self.color,
                "width": self.width,
                "label": self.label,
            },
        )
        return self.target


__all__ = ["LevelMarker"]
