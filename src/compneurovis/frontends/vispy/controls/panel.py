from __future__ import annotations

import math
from typing import Any

from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt

from compneurovis.core.controls import (
    ActionSpec,
    ControlPresentationSpec,
    ControlSpec,
    ControlValueSpec,
)
from compneurovis.frontends.vispy.registries.controls import action_renderer, control_renderer
from compneurovis.frontends.vispy.bindings import resolve_binding
from .xy_pad import XYPadWidget

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
