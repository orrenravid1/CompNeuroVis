"""Shared QWidget host substrate for sibling Plot2D renderers."""

from __future__ import annotations

import time
from typing import Any

from PyQt6 import QtWidgets

from compneurovis.core.field import Field
from compneurovis.core.runtime.performance import perf_log


class Plot2DHostPanel(QtWidgets.QGroupBox):
    """Own the common titled host, contribution surface, and render timing."""

    visual_contribution_capabilities = ("plot2d.layers/v1",)
    canvas_type: Any = None

    def __init__(
        self,
        *,
        panel_id: str,
        view_id: str,
        title: str | None = None,
        show_internal_title: bool = True,
        parent=None,
    ):
        if self.canvas_type is None:
            raise TypeError("Plot2DHostPanel subclasses must declare canvas_type")
        host_title = str(title) if title else None
        super().__init__(host_title or "", parent)
        self._host_title = host_title
        self.panel_id = panel_id
        self.view_id = view_id
        self.plot_2d_panel = self.canvas_type(
            show_internal_title=show_internal_title,
            perf_panel_id=panel_id,
            perf_view_id=view_id,
        )
        self.visual_contribution_surface = self.plot_2d_panel
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.addWidget(self.plot_2d_panel)

    def _render(
        self,
        view: Any,
        field: Field | None,
        values: dict[str, Any],
    ) -> None:
        started = time.monotonic()
        self.plot_2d_panel.refresh(view, field, values)
        self.setTitle(self._host_title or "")
        if view is None:
            return
        duration_ms = round((time.monotonic() - started) * 1000.0, 3)
        if duration_ms >= 5.0:
            perf_log(
                "plot2d",
                "refresh",
                panel_id=self.panel_id,
                view_id=self.view_id,
                field_id=getattr(view, "field_id", None),
                duration_ms=duration_ms,
                field_shape=getattr(getattr(field, "values", None), "shape", None),
                panel_width_px=self.plot_2d_panel.width(),
                panel_height_px=self.plot_2d_panel.height(),
            )


__all__ = ["Plot2DHostPanel"]
