"""Source-level widget authoring API and built-in widgets."""

from compneurovis.inline.widgets.api import Widget, WidgetAuthoringContext
from compneurovis.inline.widgets.bar import BarWidget
from compneurovis.inline.widgets.grid_slice import GridSlice
from compneurovis.inline.widgets.line import LineWidget
from compneurovis.inline.widgets.morphology import Morphology
from compneurovis.inline.widgets.network2d import Network2D
from compneurovis.inline.widgets.surface import Surface

__all__ = [
    "BarWidget",
    "GridSlice",
    "LineWidget",
    "Morphology",
    "Network2D",
    "Surface",
    "Widget",
    "WidgetAuthoringContext",
]
