"""Public contracts for reusable source-level widgets."""

from compneurovis.inline.handles import DataHandle, PanelHandle
from compneurovis.inline.widget_authoring import (
    BarWidget,
    LineWidget,
    Network2D,
    Widget,
    WidgetAuthoringContext,
)

__all__ = [
    "BarWidget",
    "DataHandle",
    "LineWidget",
    "Network2D",
    "PanelHandle",
    "Widget",
    "WidgetAuthoringContext",
]
