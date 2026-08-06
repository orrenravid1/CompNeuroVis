from __future__ import annotations

import math
from typing import Any

from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt

from compneurovis.core.controls import (
    ActionSpec,
    ControlSpec,
)
from compneurovis.frontends.vispy.registries.controls import (
    ControlRenderContext,
    action_renderer,
    control_renderer,
)
from compneurovis.frontends.vispy.bindings import resolve_binding

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
            context = ControlRenderContext(
                lambda value, spec=control: self.on_value_changed(spec, value)
            )
            widget = registration.factory(context, control, current)
            if not isinstance(widget, QtWidgets.QWidget):
                raise TypeError(
                    f"Vispy control renderer {control.presentation.kind!r} "
                    "must return a QWidget"
                )
            self.widgets[control.id] = widget
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
            widget = registration.factory(self, action, self._values)
            self.widgets[action.id] = widget
            self._grid.addWidget(widget, row, column)

        if self._actions:
            row_index += math.ceil(len(self._actions) / column_count)

        self._grid.setRowStretch(row_index, 1)

    def _clear_grid(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _control_current_value(self, control: ControlSpec, values: dict[str, Any]):
        return values.get(control.resolved_value_key(), control.default_value())

    def _build_action_button(self, action: ActionSpec, values: dict[str, Any]) -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton(action.label)
        button.clicked.connect(lambda _checked=False, spec=action: self._invoke_action(spec, values))
        if action.shortcuts:
            button.setToolTip(f"Shortcut: {', '.join(action.shortcuts)}")
        self.widgets[action.id] = button
        return button

    def _invoke_action(self, action: ActionSpec, values: dict[str, Any]) -> None:
        if self.on_action_invoked is None:
            return
        payload = {
            key: resolve_binding(value, values)
            for key, value in action.payload.items()
        }
        self.on_action_invoked(action, payload)
