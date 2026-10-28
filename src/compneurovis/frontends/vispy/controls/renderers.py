"""First-party control renderer implementations and explicit registration."""

from __future__ import annotations

import math
from typing import Any

from PyQt6 import QtWidgets
from PyQt6.QtCore import QSignalBlocker, Qt

from compneurovis.core.controls import ControlSpec
from compneurovis.frontends.vispy.registries.controls import (
    ControlRenderContext,
    register_control_renderer,
)
from .xy_pad import XYPadWidget


def _row_shell(
    control: ControlSpec,
) -> tuple[QtWidgets.QWidget, QtWidgets.QHBoxLayout]:
    row = QtWidgets.QWidget()
    layout = QtWidgets.QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(QtWidgets.QLabel(control.label))
    return row, layout


def _slider_raw_to_value(
    raw: int,
    *,
    min_value: float,
    max_value: float,
    steps: int,
    scale: str,
) -> float:
    fraction = raw / max(1, steps)
    if scale == "log" and min_value > 0 and max_value > min_value:
        return float(min_value * ((max_value / min_value) ** fraction))
    return float(min_value + (max_value - min_value) * fraction)


def _slider_value_to_raw(
    value: Any,
    *,
    min_value: float,
    max_value: float,
    steps: int,
    scale: str,
) -> int:
    try:
        numeric = float(value)
    except Exception:
        return 0
    if max_value <= min_value:
        return 0
    if scale == "log" and min_value > 0 and max_value > min_value:
        if numeric <= 0:
            return 0
        fraction = math.log(numeric / min_value) / math.log(max_value / min_value)
    else:
        fraction = (numeric - min_value) / (max_value - min_value)
    return int(round(min(max(fraction, 0.0), 1.0) * steps))

def _slider_renderer(
    context: ControlRenderContext, control: ControlSpec, current: Any
) -> QtWidgets.QWidget:
    row, layout = _row_shell(control)
    is_integer = control.value_spec.property("value_type", "float") == "int"
    if is_integer:
        def coerce(value):
            return int(round(value))
    else:
        coerce = float

    slider = QtWidgets.QSlider(Qt.Orientation.Horizontal)
    steps = int(control.presentation.property("steps", 100))
    slider.setRange(0, steps)
    min_value = float(control.value_spec.property("min", 0.0))
    max_value = float(control.value_spec.property("max", 1.0))
    scale = control.presentation.property("scale", "linear")
    value_label = QtWidgets.QLabel("")

    def on_change(raw: int) -> None:
        value = coerce(
            _slider_raw_to_value(
                raw,
                min_value=min_value,
                max_value=max_value,
                steps=steps,
                scale=scale,
            )
        )
        value_label.setText(str(value) if is_integer else f"{value:.3g}")
        context.emit(value)

    raw_value = _slider_value_to_raw(
        current,
        min_value=min_value,
        max_value=max_value,
        steps=steps,
        scale=scale,
    )
    slider.setValue(max(0, min(steps, raw_value)))
    slider.valueChanged.connect(on_change)
    initial_value = coerce(
        _slider_raw_to_value(
            slider.value(),
            min_value=min_value,
            max_value=max_value,
            steps=steps,
            scale=scale,
        )
    )
    value_label.setText(
        str(initial_value) if is_integer else f"{initial_value:.3g}"
    )
    layout.addWidget(slider, 1)
    layout.addWidget(value_label)
    row._cnv_slider = slider
    row._cnv_value_label = value_label
    return row


def _update_slider(row, control: ControlSpec, current: Any) -> None:
    slider = row._cnv_slider
    value_label = row._cnv_value_label
    steps = int(control.presentation.property("steps", 100))
    min_value = float(control.value_spec.property("min", 0.0))
    max_value = float(control.value_spec.property("max", 1.0))
    scale = control.presentation.property("scale", "linear")
    is_integer = control.value_spec.property("value_type", "float") == "int"
    raw_value = _slider_value_to_raw(
        current,
        min_value=min_value,
        max_value=max_value,
        steps=steps,
        scale=scale,
    )
    blocker = QSignalBlocker(slider)
    slider.setValue(max(0, min(steps, raw_value)))
    del blocker
    displayed = _slider_raw_to_value(
        slider.value(),
        min_value=min_value,
        max_value=max_value,
        steps=steps,
        scale=scale,
    )
    value_label.setText(
        str(int(round(displayed))) if is_integer else f"{displayed:.3g}"
    )


def _spinbox_renderer(
    context: ControlRenderContext, control: ControlSpec, current: Any
) -> QtWidgets.QWidget:
    row, layout = _row_shell(control)
    spin = QtWidgets.QSpinBox()
    spin.setRange(
        int(control.value_spec.property("min", 0)),
        int(control.value_spec.property("max", 100)),
    )
    spin.setValue(int(current))
    spin.valueChanged.connect(lambda value: context.emit(int(value)))
    layout.addWidget(spin)
    row._cnv_spinbox = spin
    return row


def _update_spinbox(row, control: ControlSpec, current: Any) -> None:
    del control
    blocker = QSignalBlocker(row._cnv_spinbox)
    row._cnv_spinbox.setValue(int(current))
    del blocker


def _checkbox_renderer(
    context: ControlRenderContext, control: ControlSpec, current: Any
) -> QtWidgets.QWidget:
    row, layout = _row_shell(control)
    checkbox = QtWidgets.QCheckBox()
    checkbox.setChecked(bool(current))
    checkbox.toggled.connect(lambda value: context.emit(bool(value)))
    layout.addWidget(checkbox)
    row._cnv_checkbox = checkbox
    return row


def _update_checkbox(row, control: ControlSpec, current: Any) -> None:
    del control
    blocker = QSignalBlocker(row._cnv_checkbox)
    row._cnv_checkbox.setChecked(bool(current))
    del blocker


def _dropdown_renderer(
    context: ControlRenderContext, control: ControlSpec, current: Any
) -> QtWidgets.QWidget:
    row, layout = _row_shell(control)
    combo = QtWidgets.QComboBox()
    options = tuple(control.value_spec.property("options", ()))
    combo.addItems([str(option) for option in options])
    if current in options:
        combo.setCurrentIndex(options.index(current))
    combo.currentIndexChanged.connect(
        lambda index: context.emit(options[int(index)])
    )
    layout.addWidget(combo)
    row._cnv_combo = combo
    return row


def _update_dropdown(row, control: ControlSpec, current: Any) -> None:
    options = tuple(control.value_spec.property("options", ()))
    index = options.index(current) if current in options else -1
    blocker = QSignalBlocker(row._cnv_combo)
    row._cnv_combo.setCurrentIndex(index)
    del blocker


def _text_renderer(
    context: ControlRenderContext, control: ControlSpec, current: Any
) -> QtWidgets.QWidget:
    row, layout = _row_shell(control)
    line_edit = QtWidgets.QLineEdit()
    line_edit.setText(
        str(current if current is not None else control.value_spec.default)
    )
    placeholder = control.value_spec.property("placeholder", "")
    max_length = control.value_spec.property("max_length")
    if placeholder:
        line_edit.setPlaceholderText(placeholder)
    if max_length is not None:
        line_edit.setMaxLength(int(max_length))
    line_edit.textChanged.connect(lambda value: context.emit(str(value)))
    layout.addWidget(line_edit, 1)
    row._cnv_line_edit = line_edit
    return row


def _update_text(row, control: ControlSpec, current: Any) -> None:
    value = str(current if current is not None else control.value_spec.default)
    if row._cnv_line_edit.text() == value:
        return
    blocker = QSignalBlocker(row._cnv_line_edit)
    row._cnv_line_edit.setText(value)
    del blocker


def _xy_pad_renderer(
    context: ControlRenderContext, control: ControlSpec, current: Any
) -> QtWidgets.QWidget:
    wrapper = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout(wrapper)
    layout.setContentsMargins(0, 2, 0, 2)
    layout.setSpacing(2)
    if control.label:
        layout.addWidget(QtWidgets.QLabel(control.label))
    if not isinstance(current, dict):
        current = control.default_value()
    pad = XYPadWidget(control, current, context.emit)
    layout.addWidget(pad)
    wrapper._cnv_xy_pad = pad
    return wrapper


def _update_xy_pad(wrapper, control: ControlSpec, current: Any) -> None:
    if not isinstance(current, dict):
        current = control.default_value()
    wrapper._cnv_xy_pad.set_values(current)


def _button_renderer(
    context: ControlRenderContext, control: ControlSpec, current: Any
) -> QtWidgets.QWidget:
    # A trigger control carries no value, so the emitted payload is unused; the
    # frontend routes a trigger emit as an invocation rather than a value change.
    del current
    button = QtWidgets.QPushButton(control.label)
    button.clicked.connect(lambda _checked=False: context.emit(None))
    return button


def _update_button(button, control: ControlSpec, current: Any) -> None:
    del button, control, current




def register_first_party_control_renderers() -> None:
    register_control_renderer("slider", _slider_renderer, updater=_update_slider)
    register_control_renderer("spinbox", _spinbox_renderer, updater=_update_spinbox)
    register_control_renderer("checkbox", _checkbox_renderer, updater=_update_checkbox)
    register_control_renderer("dropdown", _dropdown_renderer, updater=_update_dropdown)
    register_control_renderer("text", _text_renderer, updater=_update_text)
    register_control_renderer(
        "xy_pad", _xy_pad_renderer, full_width=True, updater=_update_xy_pad
    )
    register_control_renderer("button", _button_renderer, updater=_update_button)


__all__ = ["register_first_party_control_renderers"]
