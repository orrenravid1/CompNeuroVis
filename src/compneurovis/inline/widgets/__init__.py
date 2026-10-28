"""Source-level widget authoring API and built-in widgets."""

from compneurovis.inline.widgets.api import Widget, WidgetAuthoringContext
from compneurovis.components.bar.authoring import Bar
from compneurovis.components.grid_slice.authoring import GridSlice
from compneurovis.components.level_marker.authoring import LevelMarker
from compneurovis.components.line.authoring import Line
from compneurovis.components.morphology.authoring import Morphology
from compneurovis.components.network2d.authoring import Network2D
from compneurovis.components.surface.authoring import Surface

__all__ = [
    "Bar",
    "GridSlice",
    "LevelMarker",
    "Line",
    "Morphology",
    "Network2D",
    "Surface",
    "Widget",
    "WidgetAuthoringContext",
]
