from __future__ import annotations

from typing import Any

from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt

from compneurovis.core import AppRef
from compneurovis.frontends.vispy.registries.controls import (
    ControlRenderContext,
    ResolvedControl,
    control_renderer,
)


class ControlsPanel(QtWidgets.QWidget):
    _MULTI_COLUMN_MIN_WIDTH = 900
    _MULTI_COLUMN_MIN_ITEMS = 8
    _CONTROL_FONT_POINT_SIZE = 11

    def __init__(self, on_value_changed, parent=None):
        super().__init__(parent)
        font = self.font()
        if font.pointSize() > 0:
            font.setPointSize(max(font.pointSize(), self._CONTROL_FONT_POINT_SIZE))
            self.setFont(font)
        self.on_value_changed = on_value_changed
        self.widgets: dict[AppRef, QtWidgets.QWidget] = {}
        self._render_contexts: list[Any] = []
        self._controls: list[ResolvedControl] = []
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
        values: dict[Any, Any],
    ) -> None:
        controls = list(controls)
        can_update = self._can_update_in_place(controls)
        self._controls = controls
        self._values = values
        if can_update:
            self._update_values()
        else:
            self._rebuild_grid(force=True)

    def _can_update_in_place(self, controls: list[ResolvedControl]) -> bool:
        if controls != self._controls:
            return False
        visible = [resolved for resolved in controls if resolved.spec.visible]
        return all(
            resolved.ref in self.widgets
            for resolved in visible
        )

    def _update_values(self) -> None:
        for resolved in self._visible_controls():
            registration = control_renderer(resolved.spec.presentation.kind)
            registration.updater(
                self.widgets[resolved.ref],
                resolved.spec,
                self._control_current_value(resolved, self._values),
            )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._rebuild_grid(force=False)

    def _desired_column_count(self) -> int:
        compact_controls = sum(
            1
            for resolved in self._visible_controls()
            if not control_renderer(resolved.spec.presentation.kind).full_width
        )
        item_count = compact_controls
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

