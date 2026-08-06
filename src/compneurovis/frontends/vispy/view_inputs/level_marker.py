"""Plot2D contribution renderer for authored reference lines."""

from __future__ import annotations

import pyqtgraph as pg

from compneurovis.frontends.vispy.visual_contributions import (
    register_plot_contribution,
)


LEVEL_MARKER_KIND = "level_marker"


class LevelMarkerRenderer:
    def __init__(self, context, spec) -> None:
        del spec
        self._plot = context.surface
        self._line = pg.InfiniteLine(angle=0, movable=False)
        self._plot.addItem(self._line, ignoreBounds=True)
        self._line.hide()
        self._signature = None

    def refresh(
        self, spec, inputs, geometries, selections, properties, values
    ) -> None:
        del spec, inputs, geometries, selections, values
        value = properties.get("value")
        if value is None:
            self._line.hide()
            return
        orientation = str(properties.get("orientation", "horizontal"))
        color = properties.get("color", "#d62728")
        width = float(properties.get("width", 2.0))
        signature = (orientation, color, width)
        if signature != self._signature:
            self._line.setAngle(0.0 if orientation == "horizontal" else 90.0)
            self._line.setPen(pg.mkPen(color, width=width))
            self._signature = signature
        self._line.setValue(float(value))
        self._line.show()

    def clear(self) -> None:
        self._plot.removeItem(self._line)


register_plot_contribution(LEVEL_MARKER_KIND, LevelMarkerRenderer)


__all__ = ["LEVEL_MARKER_KIND", "LevelMarkerRenderer"]
