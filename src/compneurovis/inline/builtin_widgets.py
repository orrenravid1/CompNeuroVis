"""Built-in widgets registered through the public authoring contract."""

from __future__ import annotations

from compneurovis.inline.widget_registry import _register_first_party_widget
from compneurovis.inline.widgets import (
    Bar,
    GridSlice,
    LevelMarker,
    Line,
    Morphology,
    Network2D,
    Surface,
)


def register_builtin_widgets() -> None:
    """Install all first-party widget factories in the shared registry."""
    _register_first_party_widget("line", Line)
    _register_first_party_widget("bar", Bar)
    _register_first_party_widget("network2d", Network2D)
    _register_first_party_widget("morphology", Morphology)
    _register_first_party_widget("surface", Surface)
    _register_first_party_widget("grid_slice", GridSlice)
    _register_first_party_widget("level_marker", LevelMarker)


__all__ = ["register_builtin_widgets"]
