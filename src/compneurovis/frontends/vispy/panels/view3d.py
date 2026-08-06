from __future__ import annotations

import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets

from compneurovis.core.app_spec import PanelSpec
from compneurovis.frontends.vispy.renderers.colormaps import _colormap_samples
from compneurovis.frontends.vispy.view3d.viewport import Viewport3DPanel
from compneurovis.frontends.vispy.view3d.visuals import create_scene_layers


class Colorbar3DWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._color_map = "scalar"
        self._vmin = 0.0
        self._vmax = 1.0
        self._label = ""
        self.setMinimumHeight(52)
        self.setMaximumHeight(58)
        self.setVisible(False)

    def set_scale(self, *, color_map: str, vmin: float, vmax: float, label: str = "") -> None:
        self._color_map = str(color_map)
        self._vmin = float(vmin)
        self._vmax = float(vmax)
        self._label = str(label)
        self.setVisible(True)
        self.update()

    def clear(self) -> None:
        self.setVisible(False)

    def paintEvent(self, event) -> None:
        del event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(10, 8, -10, -18)
        bar_height = 12
        bar_rect = QtCore.QRectF(rect.left(), rect.bottom() - bar_height, rect.width(), bar_height)

        gradient = QtGui.QLinearGradient(bar_rect.left(), bar_rect.center().y(), bar_rect.right(), bar_rect.center().y())
        samples = self._samples()
        for index, rgba in enumerate(samples):
            color = QtGui.QColor.fromRgbF(float(rgba[0]), float(rgba[1]), float(rgba[2]), float(rgba[3]))
            gradient.setColorAt(index / max(1, len(samples) - 1), color)

        painter.setPen(QtGui.QPen(QtGui.QColor(70, 70, 70), 1.0))
        painter.setBrush(QtGui.QBrush(gradient))
        painter.drawRect(bar_rect)

        font = painter.font()
        font.setPointSize(max(9, font.pointSize()))
        painter.setFont(font)
        painter.setPen(QtGui.QColor(25, 25, 25))
        if self._label:
            painter.drawText(rect.left(), rect.top(), self._label)
        painter.drawText(QtCore.QPointF(bar_rect.left(), bar_rect.bottom() + 14), self._format_value(self._vmin))
        max_text = self._format_value(self._vmax)
        text_width = painter.fontMetrics().horizontalAdvance(max_text)
        painter.drawText(QtCore.QPointF(bar_rect.right() - text_width, bar_rect.bottom() + 14), max_text)
        painter.end()

    def _samples(self) -> np.ndarray:
        if self._color_map.strip().lower() == "scalar":
            x = np.linspace(0.0, 1.0, 32, dtype=np.float32)
            return np.stack((x, np.full_like(x, 0.2), 1.0 - x, np.ones_like(x)), axis=1)
        return _colormap_samples(self._color_map, n=32)

    def _format_value(self, value: float) -> str:
        if abs(value) >= 10:
            return f"{value:.0f}"
        return f"{value:.2g}"


class IndependentCanvas3DHostPanel(QtWidgets.QGroupBox):
    visual_contribution_capabilities = ("scene3d.layers/v1",)

    def __init__(
        self,
        *,
        panel: PanelSpec,
        visual_kind: str,
        title: str | None = None,
        camera=None,
        on_entity_selected=None,
        parent=None,
    ):
        super().__init__(title or panel.view_ids[0], parent)
        self.panel_id = panel.id
        self.view_ids = panel.view_ids
        scoped_selection_handler = (
            None
            if on_entity_selected is None
            else lambda entity_id: on_entity_selected(panel.view_ids[0], entity_id)
        )
        self.viewport = Viewport3DPanel(
            host_spec=panel,
            camera=camera,
            on_entity_selected=scoped_selection_handler,
        )
        self.visual_contribution_surface = self.viewport.view
        for key, visual in create_scene_layers(
            self.viewport.view,
            kind=visual_kind,
            panel_id=self.panel_id,
        ).items():
            self.viewport.mount_visual(key, visual)
        self.colorbar = Colorbar3DWidget()
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.addWidget(self.viewport)
        layout.addWidget(self.colorbar)

    def clear(self) -> None:
        self.viewport.clear()
        self.colorbar.clear()

    def activate_visual(self, view_id: str, visual_key: str, *, view=None):
        if view_id != self.view_ids[0]:
            return None
        return self.viewport.activate_visual(visual_key, view=view)

    def visual_for_kind(self, kind: str):
        # The visual mounted under a view's own kind is its primary visual (the one
        # that owns panel overlays); returns None if the panel has no such visual.
        try:
            return self.viewport.visual(kind)
        except ValueError:
            return None

    def visual(self, visual_key: str):
        return self.viewport.visual(visual_key)

    def set_background(self, color) -> None:
        self.viewport.canvas.bgcolor = color

    def commit(self) -> None:
        self.viewport.commit()

    def set_colorbar(self, *, color_map: str, vmin: float, vmax: float, label: str = "") -> None:
        self.colorbar.set_scale(color_map=color_map, vmin=vmin, vmax=vmax, label=label)

    def clear_colorbar(self) -> None:
        self.colorbar.clear()
