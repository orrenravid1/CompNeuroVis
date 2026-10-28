from __future__ import annotations

from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt

from compneurovis.core.controls import ControlSpec

class XYPadWidget(QtWidgets.QWidget):
    _HANDLE_RADIUS = 7
    _PAD_MARGIN = 14

    def __init__(self, control: ControlSpec, value: dict[str, float], on_changed, parent=None):
        super().__init__(parent)
        self._control = control
        self._spec = control.value_spec
        self._presentation = control.presentation
        default = control.default_value()
        self._x_norm = self._to_norm_x(float(value.get("x", default["x"])))
        self._y_norm = self._to_norm_y(float(value.get("y", default["y"])))
        self._dragging = False
        self._on_changed = on_changed
        self.setMinimumSize(160, 175)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)

    def _to_norm_x(self, value: float) -> float:
        x_min, x_max = self._spec.property("x_range", (0.0, 1.0))
        span = x_max - x_min
        return max(0.0, min(1.0, (value - x_min) / span)) if span else 0.5

    def _to_norm_y(self, value: float) -> float:
        y_min, y_max = self._spec.property("y_range", (0.0, 1.0))
        span = y_max - y_min
        return max(0.0, min(1.0, (value - y_min) / span)) if span else 0.5

    def _pad_rect(self) -> tuple[int, int, int, int]:
        m = self._PAD_MARGIN
        label_reserve = 18
        w = self.width() - 2 * m
        h = self.height() - 2 * m - label_reserve
        side = max(1, min(w, h))
        x0 = m + (w - side) // 2
        y0 = m
        return x0, y0, side, side

    def _norm_to_pixel(self, nx: float, ny: float) -> tuple[float, float]:
        x0, y0, w, h = self._pad_rect()
        return x0 + nx * w, y0 + (1.0 - ny) * h

    def _pixel_to_norm(self, px: float, py: float) -> tuple[float, float]:
        x0, y0, w, h = self._pad_rect()
        nx = max(0.0, min(1.0, (px - x0) / w)) if w else 0.5
        ny = max(0.0, min(1.0, 1.0 - (py - y0) / h)) if h else 0.5
        return nx, ny

    def _norm_to_values(self, nx: float, ny: float) -> dict[str, float]:
        x_min, x_max = self._spec.property("x_range", (0.0, 1.0))
        y_min, y_max = self._spec.property("y_range", (0.0, 1.0))
        return {
            "x": float(x_min + nx * (x_max - x_min)),
            "y": float(y_min + ny * (y_max - y_min)),
        }

    def paintEvent(self, event) -> None:
        from PyQt6.QtGui import QPainter, QColor, QPen, QBrush, QPainterPath
        from PyQt6.QtCore import QRectF, QPointF

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        x0, y0, w, h = self._pad_rect()
        pad_rect = QRectF(x0, y0, w, h)
        bg = QColor(40, 40, 45)
        border = QColor(80, 80, 92)
        grid_color = QColor(60, 60, 70)

        if self._presentation.property("shape", "square") == "circle":
            painter.setBrush(QBrush(bg))
            painter.setPen(QPen(border, 1.5))
            painter.drawEllipse(pad_rect)
            clip = QPainterPath()
            clip.addEllipse(pad_rect)
            painter.setClipPath(clip)
        else:
            painter.setBrush(QBrush(bg))
            painter.setPen(QPen(border, 1.5))
            painter.drawRoundedRect(pad_rect, 4.0, 4.0)

        cx, cy = self._norm_to_pixel(0.5, 0.5)
        painter.setPen(QPen(grid_color, 1, Qt.PenStyle.DashLine))
        painter.drawLine(QPointF(x0, cy), QPointF(x0 + w, cy))
        painter.drawLine(QPointF(cx, y0), QPointF(cx, y0 + h))

        painter.setClipping(False)

        hx, hy = self._norm_to_pixel(self._x_norm, self._y_norm)
        r = self._HANDLE_RADIUS

        painter.setBrush(QBrush(QColor(100, 180, 255, 55)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QRectF(hx - r - 4, hy - r - 4, (r + 4) * 2, (r + 4) * 2))

        painter.setBrush(QBrush(QColor(100, 180, 255)))
        painter.setPen(QPen(QColor(210, 235, 255), 1.5))
        painter.drawEllipse(QRectF(hx - r, hy - r, r * 2, r * 2))

        value = self._norm_to_values(self._x_norm, self._y_norm)
        painter.setPen(QPen(QColor(155, 155, 175)))
        font = painter.font()
        font.setPointSize(8)
        painter.setFont(font)
        x_label = self._spec.property("x_label", "X")
        y_label = self._spec.property("y_label", "Y")
        label = f"{x_label}: {value['x']:.3g}   {y_label}: {value['y']:.3g}"
        painter.drawText(int(x0), int(y0 + h + self._PAD_MARGIN), label)

        painter.end()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._update_from_pos(event.position().x(), event.position().y())

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self._update_from_pos(event.position().x(), event.position().y())

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False

    def _update_from_pos(self, px: float, py: float) -> None:
        nx, ny = self._pixel_to_norm(px, py)
        self._x_norm = nx
        self._y_norm = ny
        self._on_changed(self._norm_to_values(nx, ny))
        self.update()

    def set_values(self, value: dict[str, float]) -> None:
        default = self._control.default_value()
        self._x_norm = self._to_norm_x(float(value.get("x", default["x"])))
        self._y_norm = self._to_norm_y(float(value.get("y", default["y"])))
        self.update()
