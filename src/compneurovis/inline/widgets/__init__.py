"""Source-level widget authoring API and built-in widgets."""

from compneurovis.inline.widgets.api import Widget, WidgetAuthoringContext
from compneurovis.inline.widgets.bar import Bar
from compneurovis.inline.widgets.grid_slice import GridSlice
from compneurovis.inline.widgets.line import Line
from compneurovis.inline.widgets.morphology import Morphology
from compneurovis.inline.widgets.morphology_geometry import MorphologyGeometry
from compneurovis.inline.widgets.network2d import Network2D
from compneurovis.inline.widgets.surface import Surface

__all__ = [
    "Bar",
    "GridSlice",
    "Line",
    "Morphology",
    "MorphologyGeometry",
    "Network2D",
    "Surface",
    "Widget",
    "WidgetAuthoringContext",
]
