from __future__ import annotations

import math
from typing import Any

from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt

from compneurovis.core.controls import (
    ActionSpec,
    ControlSpec,
    ControlValueSpec,
    ControlPresentationSpec,
)
from compneurovis.frontends.vispy.control_renderers import (
    action_renderer,
    control_renderer,
    register_action_renderer,
    register_control_renderer,
)
from compneurovis.frontends.vispy.view_inputs.bindings import resolve_binding


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


class ControlsPanel(QtWidgets.QWidget):
    _MULTI_COLUMN_MIN_WIDTH = 900
    _MULTI_COLUMN_MIN_ITEMS = 8
    _CONTROL_FONT_POINT_SIZE = 11

    def __init__(self, on_value_changed, on_action_invoked=None, parent=None):
        super().__init__(parent)
        font = self.font()
        if font.pointSize() > 0:
            font.setPointSize(max(font.pointSize(), self._CONTROL_FONT_POINT_SIZE))
            self.setFont(font)
        self.on_value_changed = on_value_changed
        self.on_action_invoked = on_action_invoked
        self.widgets: dict[str, QtWidgets.QWidget] = {}
        self._controls: list[ControlSpec] = []
        self._actions: list[ActionSpec] = []
        self._values: dict[str, Any] = {}
        self._column_count = 1
        self._grid = QtWidgets.QGridLayout(self)
        self._grid.setContentsMargins(6, 6, 6, 6)
        self._grid.setHorizontalSpacing(10)
        self._grid.setVerticalSpacing(6)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop)

    def set_controls(self, controls: list[ControlSpec], actions: list[ActionSpec], values: dict[str, Any]) -> None:
        self._controls = list(controls)
        self._actions = list(actions)
        self._values = values
        self._rebuild_grid(force=True)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._rebuild_grid(force=False)

    def _desired_column_count(self) -> int:
        compact_controls = sum(
            1
            for control in self._controls
            if not control_renderer(control.presentation.kind).full_width
        )
        compact_actions = sum(
            1
            for action in self._actions
            if not action_renderer(action.presentation_kind).full_width
        )
        item_count = compact_controls + compact_actions
        if item_count < self._MULTI_COLUMN_MIN_ITEMS:
            return 1
        if self.width() < self._MULTI_COLUMN_MIN_WIDTH:
            return 1
        return 2

    def _rebuild_grid(self, *, force: bool) -> None:
        column_count = self._desired_column_count()
        if not force and column_count == self._column_count:
            return

        self._column_count = column_count
        self._clear_grid()
        self.widgets.clear()

        for column in range(column_count):
            self._grid.setColumnStretch(column, 1)

        row_index = 0
        current_col = 0
        for control in self._controls:
            registration = control_renderer(control.presentation.kind)
            current = self._control_current_value(control, self._values)
            widget = registration.factory(self, control, current)
            if registration.full_width:
                if current_col > 0:
                    row_index += 1
                    current_col = 0
                self._grid.addWidget(widget, row_index, 0, 1, column_count)
                row_index += 1
            else:
                self._grid.addWidget(widget, row_index, current_col)
                current_col += 1
                if current_col >= column_count:
                    current_col = 0
                    row_index += 1
        if current_col > 0:
            row_index += 1

        if self._controls and self._actions:
            divider = QtWidgets.QFrame()
            divider.setFrameShape(QtWidgets.QFrame.Shape.HLine)
            divider.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
            self._grid.addWidget(divider, row_index, 0, 1, column_count)
            row_index += 1

        for index, action in enumerate(self._actions):
            row = row_index + (index // column_count)
            column = index % column_count
            registration = action_renderer(action.presentation_kind)
            self._grid.addWidget(
                registration.factory(self, action, self._values), row, column
            )

        if self._actions:
            row_index += math.ceil(len(self._actions) / column_count)

        self._grid.setRowStretch(row_index, 1)

    def _clear_grid(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _control_row_shell(self, control: ControlSpec) -> tuple[QtWidgets.QWidget, QtWidgets.QHBoxLayout]:
        row = QtWidgets.QWidget()
        row_layout = QtWidgets.QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(QtWidgets.QLabel(control.label))
        return row, row_layout

    def _control_current_value(self, control: ControlSpec, values: dict[str, Any]):
        return values.get(control.resolved_value_key(), control.default_value())

    def _add_float_control(
        self,
        row_layout: QtWidgets.QHBoxLayout,
        control: ControlSpec,
        value_spec: ControlValueSpec,
        presentation: ControlPresentationSpec,
        current: Any,
    ) -> None:
        slider = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        steps = int(presentation.property("steps", 100))
        slider.setRange(0, steps)
        min_value = float(value_spec.property("min", 0.0))
        max_value = float(value_spec.property("max", 1.0))
        value_label = QtWidgets.QLabel("")

        def on_change(raw: int, *, spec=control, label=value_label) -> None:
            scale = spec.presentation.property("scale", "linear")
            value = self._slider_raw_to_value(
                raw,
                min_value=min_value,
                max_value=max_value,
                steps=steps,
                scale=scale,
            )
            label.setText(f"{value:.3g}")
            self.on_value_changed(spec, value)

        raw_value = self._slider_value_to_raw(
            current,
            min_value=min_value,
            max_value=max_value,
            steps=steps,
            scale=presentation.property("scale", "linear"),
        )
        slider.setValue(max(0, min(steps, raw_value)))
        slider.valueChanged.connect(on_change)
        initial_value = self._slider_raw_to_value(
            slider.value(),
            min_value=min_value,
            max_value=max_value,
            steps=steps,
            scale=presentation.property("scale", "linear"),
        )
        value_label.setText(f"{initial_value:.3g}")
        row_layout.addWidget(slider, 1)
        row_layout.addWidget(value_label)
        self.widgets[control.id] = slider

    def _add_int_control(
        self,
        row_layout: QtWidgets.QHBoxLayout,
        control: ControlSpec,
        value_spec: ControlValueSpec,
        presentation: ControlPresentationSpec,
        current: Any,
    ) -> None:
        spin = QtWidgets.QSpinBox()
        spin.setRange(
            int(value_spec.property("min", 0)),
            int(value_spec.property("max", 100)),
        )
        spin.setValue(int(current))
        spin.valueChanged.connect(lambda value, spec=control: self.on_value_changed(spec, int(value)))
        row_layout.addWidget(spin)
        self.widgets[control.id] = spin

    def _add_int_slider_control(
        self,
        row_layout: QtWidgets.QHBoxLayout,
        control: ControlSpec,
        value_spec: ControlValueSpec,
        presentation: ControlPresentationSpec,
        current: Any,
    ) -> None:
        slider = QtWidgets.QSlider(Qt.Orientation.Horizontal)
        steps = int(presentation.property("steps", 100))
        slider.setRange(0, steps)
        min_value = float(value_spec.property("min", 0.0))
        max_value = float(value_spec.property("max", 1.0))
        value_label = QtWidgets.QLabel("")

        def on_change(raw: int, *, spec=control, label=value_label) -> None:
            scale = spec.presentation.property("scale", "linear")
            value = int(round(self._slider_raw_to_value(
                raw,
                min_value=min_value,
                max_value=max_value,
                steps=steps,
                scale=scale,
            )))
            label.setText(str(value))
            self.on_value_changed(spec, value)

        raw_value = self._slider_value_to_raw(
            current,
            min_value=min_value,
            max_value=max_value,
            steps=steps,
            scale=presentation.property("scale", "linear"),
        )
        slider.setValue(max(0, min(steps, raw_value)))
        slider.valueChanged.connect(on_change)
        value_label.setText(str(int(round(float(current)))))
        row_layout.addWidget(slider, 1)
        row_layout.addWidget(value_label)
        self.widgets[control.id] = slider

    def _add_bool_control(
        self,
        row_layout: QtWidgets.QHBoxLayout,
        control: ControlSpec,
        presentation: ControlPresentationSpec,
        current: Any,
    ) -> None:
        checkbox = QtWidgets.QCheckBox()
        checkbox.setChecked(bool(current))
        checkbox.toggled.connect(lambda value, spec=control: self.on_value_changed(spec, bool(value)))
        row_layout.addWidget(checkbox)
        self.widgets[control.id] = checkbox

    def _add_choice_control(
        self,
        row_layout: QtWidgets.QHBoxLayout,
        control: ControlSpec,
        value_spec: ControlValueSpec,
        presentation: ControlPresentationSpec,
        current: Any,
    ) -> None:
        combo = QtWidgets.QComboBox()
        options = tuple(value_spec.property("options", ()))
        combo.addItems([str(option) for option in options])
        if str(current) in options:
            combo.setCurrentIndex(options.index(str(current)))
        combo.currentIndexChanged.connect(
            lambda idx, spec=control, options=options: self.on_value_changed(spec, options[int(idx)])
        )
        row_layout.addWidget(combo)
        self.widgets[control.id] = combo

    def _add_text_control(
        self,
        row_layout: QtWidgets.QHBoxLayout,
        control: ControlSpec,
        value_spec: ControlValueSpec,
        presentation: ControlPresentationSpec,
        current: Any,
    ) -> None:
        line_edit = QtWidgets.QLineEdit()
        line_edit.setText(str(current if current is not None else value_spec.default))
        placeholder = value_spec.property("placeholder", "")
        max_length = value_spec.property("max_length")
        if placeholder:
            line_edit.setPlaceholderText(placeholder)
        if max_length is not None:
            line_edit.setMaxLength(int(max_length))
        line_edit.textChanged.connect(lambda value, spec=control: self.on_value_changed(spec, str(value)))
        row_layout.addWidget(line_edit, 1)
        self.widgets[control.id] = line_edit
    def _build_xy_pad_row(self, control: ControlSpec, current: Any) -> QtWidgets.QWidget:
        wrapper = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(2)
        if control.label:
            layout.addWidget(QtWidgets.QLabel(control.label))
        if not isinstance(current, dict):
            current = control.default_value()

        def on_xy_changed(value: dict[str, float], spec=control) -> None:
            self.on_value_changed(spec, value)

        pad = XYPadWidget(control, current, on_xy_changed)
        layout.addWidget(pad)
        self.widgets[control.id] = pad
        return wrapper

    def _build_action_button(self, action: ActionSpec, values: dict[str, Any]) -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton(action.label)
        button.clicked.connect(lambda _checked=False, spec=action: self._invoke_action(spec, values))
        if action.shortcuts:
            button.setToolTip(f"Shortcut: {', '.join(action.shortcuts)}")
        self.widgets[action.id] = button
        return button

    @staticmethod
    def _slider_raw_to_value(raw: int, *, min_value: float, max_value: float, steps: int, scale: str) -> float:
        frac = raw / max(1, steps)
        if scale == "log" and min_value > 0 and max_value > min_value:
            return float(min_value * ((max_value / min_value) ** frac))
        return float(min_value + (max_value - min_value) * frac)

    @staticmethod
    def _slider_value_to_raw(value: Any, *, min_value: float, max_value: float, steps: int, scale: str) -> int:
        try:
            numeric = float(value)
        except Exception:
            return 0
        if max_value <= min_value:
            return 0
        if scale == "log" and min_value > 0 and max_value > min_value:
            if numeric <= 0:
                return 0
            frac = math.log(numeric / min_value) / math.log(max_value / min_value)
        else:
            frac = (numeric - min_value) / (max_value - min_value)
        return int(round(min(max(frac, 0.0), 1.0) * steps))

    def _invoke_action(self, action: ActionSpec, values: dict[str, Any]) -> None:
        if self.on_action_invoked is None:
            return
        payload = {
            key: resolve_binding(value, values)
            for key, value in action.payload.items()
        }
        self.on_action_invoked(action, payload)


def _slider_renderer(
    panel: ControlsPanel, control: ControlSpec, current: Any
) -> QtWidgets.QWidget:
    row, layout = panel._control_row_shell(control)
    if control.value_spec.property("value_type", "float") == "int":
        panel._add_int_slider_control(
            layout, control, control.value_spec, control.presentation, current
        )
    else:
        panel._add_float_control(
            layout, control, control.value_spec, control.presentation, current
        )
    return row


def _spinbox_renderer(
    panel: ControlsPanel, control: ControlSpec, current: Any
) -> QtWidgets.QWidget:
    row, layout = panel._control_row_shell(control)
    panel._add_int_control(
        layout, control, control.value_spec, control.presentation, current
    )
    return row


def _checkbox_renderer(
    panel: ControlsPanel, control: ControlSpec, current: Any
) -> QtWidgets.QWidget:
    row, layout = panel._control_row_shell(control)
    panel._add_bool_control(layout, control, control.presentation, current)
    return row


def _dropdown_renderer(
    panel: ControlsPanel, control: ControlSpec, current: Any
) -> QtWidgets.QWidget:
    row, layout = panel._control_row_shell(control)
    panel._add_choice_control(
        layout, control, control.value_spec, control.presentation, current
    )
    return row


def _text_renderer(
    panel: ControlsPanel, control: ControlSpec, current: Any
) -> QtWidgets.QWidget:
    row, layout = panel._control_row_shell(control)
    panel._add_text_control(
        layout, control, control.value_spec, control.presentation, current
    )
    return row


def _xy_pad_renderer(
    panel: ControlsPanel, control: ControlSpec, current: Any
) -> QtWidgets.QWidget:
    return panel._build_xy_pad_row(control, current)


def _button_renderer(
    panel: ControlsPanel, action: ActionSpec, values: dict[str, Any]
) -> QtWidgets.QWidget:
    return panel._build_action_button(action, values)


def _register_builtin_renderers() -> None:
    register_control_renderer("slider", _slider_renderer)
    register_control_renderer("spinbox", _spinbox_renderer)
    register_control_renderer("checkbox", _checkbox_renderer)
    register_control_renderer("dropdown", _dropdown_renderer)
    register_control_renderer("text", _text_renderer)
    register_control_renderer("xy_pad", _xy_pad_renderer, full_width=True)
    register_action_renderer("button", _button_renderer)


_register_builtin_renderers()


class ControlsHostPanel(QtWidgets.QGroupBox):
    def __init__(self, controls_panel: ControlsPanel, *, panel_id: str, title: str = "Controls", parent=None):
        super().__init__(title, parent)
        self.panel_id = panel_id
        self.controls_panel = controls_panel
        self.scroll_area = QtWidgets.QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setWidget(self.controls_panel)
        self.setMinimumHeight(0)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Ignored)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.addWidget(self.scroll_area)

    def set_section_title(self, *, has_controls: bool, has_actions: bool) -> None:
        if has_controls and has_actions:
            self.setTitle("Controls & Actions")
        elif has_actions:
            self.setTitle("Actions")
        else:
            self.setTitle("Controls")
