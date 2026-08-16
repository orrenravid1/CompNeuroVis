from __future__ import annotations

import math
from typing import Any

from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt

from compneurovis.core import AppRef
from compneurovis.frontends.vispy.bindings import resolve_binding
from compneurovis.frontends.vispy.registries.controls import (
    ActionRenderContext,
    ControlRenderContext,
    ResolvedAction,
    ResolvedControl,
    action_renderer,
    control_renderer,
)


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
        self.widgets: dict[AppRef, QtWidgets.QWidget] = {}
        self._render_contexts: list[Any] = []
        self._controls: list[ResolvedControl] = []
        self._actions: list[ResolvedAction] = []
        self._values: dict[Any, Any] = {}
        self._column_count = 1
        self._grid = QtWidgets.QGridLayout(self)
        self._grid.setContentsMargins(6, 6, 6, 6)
        self._grid.setHorizontalSpacing(10)
        self._grid.setVerticalSpacing(6)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop)

    def set_controls(
        self,
        controls: list[ResolvedControl],
        actions: list[ResolvedAction],
        values: dict[Any, Any],
    ) -> None:
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
            for resolved in self._visible_controls()
            if not control_renderer(resolved.spec.presentation.kind).full_width
        )
        compact_actions = sum(
            1
            for resolved in self._actions
            if not action_renderer(resolved.spec.presentation_kind).full_width
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
        self._render_contexts.clear()

        for column in range(column_count):
            self._grid.setColumnStretch(column, 1)

        row_index = 0
        current_col = 0
        visible_controls = self._visible_controls()
        for resolved in visible_controls:
            control = resolved.spec
            registration = control_renderer(control.presentation.kind)
            current = self._control_current_value(resolved, self._values)
            context = ControlRenderContext(
                lambda value, item=resolved: self.on_value_changed(item, value)
            )
            self._render_contexts.append(context)
            widget = registration.factory(context, control, current)
            if not isinstance(widget, QtWidgets.QWidget):
                raise TypeError(
                    f"Vispy control renderer {control.presentation.kind!r} "
                    "must return a QWidget"
                )
            self.widgets[resolved.ref] = widget
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

        if visible_controls and self._actions:
            divider = QtWidgets.QFrame()
            divider.setFrameShape(QtWidgets.QFrame.Shape.HLine)
            divider.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
            self._grid.addWidget(divider, row_index, 0, 1, column_count)
            row_index += 1

        for index, resolved in enumerate(self._actions):
            action = resolved.spec
            row = row_index + (index // column_count)
            column = index % column_count
            registration = action_renderer(action.presentation_kind)
            context = ActionRenderContext(
                lambda item=resolved, values=self._values: self._invoke_action(
                    item, values
                )
            )
            self._render_contexts.append(context)
            widget = registration.factory(context, action, self._values)
            if not isinstance(widget, QtWidgets.QWidget):
                raise TypeError(
                    f"Vispy action renderer {action.presentation_kind!r} "
                    "must return a QWidget"
                )
            self.widgets[resolved.ref] = widget
            self._grid.addWidget(widget, row, column)

        if self._actions:
            row_index += math.ceil(len(self._actions) / column_count)

        self._grid.setRowStretch(row_index, 1)

    def _visible_controls(self) -> list[ResolvedControl]:
        return [
            resolved
            for resolved in self._controls
            if resolved.spec.visible
        ]

    def _clear_grid(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _control_current_value(
        self, control: ResolvedControl, values: dict[Any, Any]
    ) -> Any:
        return values.get(control.value_ref, control.spec.default_value())

    def _invoke_action(
        self, action: ResolvedAction, values: dict[Any, Any]
    ) -> None:
        if self.on_action_invoked is None:
            return
        payload = {
            key: resolve_binding(value, values, action.ref.fragment_id)
            for key, value in action.spec.payload.items()
        }
        self.on_action_invoked(action, payload)
