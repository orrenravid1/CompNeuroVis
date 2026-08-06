"""First-party control renderer implementations and explicit registration."""

from __future__ import annotations

from typing import Any

from PyQt6 import QtWidgets

from compneurovis.core.controls import ActionSpec, ControlSpec
from compneurovis.frontends.vispy.registries.controls import register_action_renderer, register_control_renderer
from .panel import ControlsPanel

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




def register_first_party_control_renderers() -> None:
    register_control_renderer("slider", _slider_renderer)
    register_control_renderer("spinbox", _spinbox_renderer)
    register_control_renderer("checkbox", _checkbox_renderer)
    register_control_renderer("dropdown", _dropdown_renderer)
    register_control_renderer("text", _text_renderer)
    register_control_renderer("xy_pad", _xy_pad_renderer, full_width=True)
    register_action_renderer("button", _button_renderer)


__all__ = ["register_first_party_control_renderers"]
