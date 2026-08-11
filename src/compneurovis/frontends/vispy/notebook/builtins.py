"""First-party notebook presentations registered through public contracts."""

from __future__ import annotations

import math
from typing import Any

from compneurovis.core.controls import ActionSpec, ControlSpec
from compneurovis.frontends.vispy.notebook.registries import (
    NotebookActionRenderContext,
    NotebookControlPresentation,
    NotebookControlRenderContext,
    register_action_renderer,
    register_control_renderer,
)

_registered = False


def _slider(
    context: NotebookControlRenderContext,
    control: ControlSpec,
    current: Any,
) -> NotebookControlPresentation:
    import ipywidgets as widgets

    minimum = float(control.value_spec.property("min", 0.0))
    maximum = float(control.value_spec.property("max", 1.0))
    steps = max(1, int(control.presentation.property("steps", 100)))
    is_integer = control.value_spec.property("value_type", "float") == "int"
    scale = str(control.presentation.property("scale", "linear"))
    if scale == "log" and minimum > 0 and maximum > minimum and not is_integer:
        widget = widgets.FloatLogSlider(
            value=float(current),
            min=math.log10(minimum),
            max=math.log10(maximum),
            step=(math.log10(maximum) - math.log10(minimum)) / steps,
            base=10,
            description=control.label,
            continuous_update=True,
            style={"description_width": "initial"},
            layout=widgets.Layout(width="95%"),
        )
        coerce = float
    elif is_integer:
        step = max(1, int(round((maximum - minimum) / steps)))
        widget = widgets.IntSlider(
            value=int(round(float(current))),
            min=int(round(minimum)),
            max=int(round(maximum)),
            step=step,
            description=control.label,
            continuous_update=True,
            style={"description_width": "initial"},
            layout=widgets.Layout(width="95%"),
        )
        def coerce(value: Any) -> int:
            return int(round(float(value)))
    else:
        widget = widgets.FloatSlider(
            value=float(current),
            min=minimum,
            max=maximum,
            step=(maximum - minimum) / steps,
            description=control.label,
            continuous_update=True,
            readout_format=".3g",
            style={"description_width": "initial"},
            layout=widgets.Layout(width="95%"),
        )
        coerce = float
    widget.observe(lambda change: context.emit(coerce(change["new"])), names="value")
    return NotebookControlPresentation(
        widget,
        lambda value: setattr(widget, "value", coerce(value)),
    )


def _spinbox(
    context: NotebookControlRenderContext,
    control: ControlSpec,
    current: Any,
) -> NotebookControlPresentation:
    import ipywidgets as widgets

    widget = widgets.BoundedIntText(
        value=int(current),
        min=int(control.value_spec.property("min", 0)),
        max=int(control.value_spec.property("max", 100)),
        description=control.label,
        style={"description_width": "initial"},
    )
    widget.observe(lambda change: context.emit(int(change["new"])), names="value")
    return NotebookControlPresentation(
        widget,
        lambda value: setattr(widget, "value", int(value)),
    )


def _dropdown(
    context: NotebookControlRenderContext,
    control: ControlSpec,
    current: Any,
) -> NotebookControlPresentation:
    import ipywidgets as widgets

    widget = widgets.Dropdown(
        options=tuple(control.value_spec.property("options", ())),
        value=current,
        description=control.label,
        style={"description_width": "initial"},
    )
    widget.observe(lambda change: context.emit(change["new"]), names="value")
    return NotebookControlPresentation(
        widget,
        lambda value: setattr(widget, "value", value),
    )


def _checkbox(
    context: NotebookControlRenderContext,
    control: ControlSpec,
    current: Any,
) -> NotebookControlPresentation:
    import ipywidgets as widgets

    widget = widgets.Checkbox(value=bool(current), description=control.label)
    widget.observe(lambda change: context.emit(bool(change["new"])), names="value")
    return NotebookControlPresentation(
        widget,
        lambda value: setattr(widget, "value", bool(value)),
    )


def _text(
    context: NotebookControlRenderContext,
    control: ControlSpec,
    current: Any,
) -> NotebookControlPresentation:
    import ipywidgets as widgets

    widget = widgets.Text(
        value=str(current),
        placeholder=str(control.value_spec.property("placeholder", "")),
        description=control.label,
        style={"description_width": "initial"},
    )
    max_length = control.value_spec.property("max_length")
    if max_length is not None:
        widget.layout.max_width = f"{max(8, int(max_length))}em"
    widget.observe(lambda change: context.emit(str(change["new"])), names="value")
    return NotebookControlPresentation(
        widget,
        lambda value: setattr(widget, "value", str(value)),
    )


def _xy_pad(
    context: NotebookControlRenderContext,
    control: ControlSpec,
    current: Any,
) -> NotebookControlPresentation:
    import ipywidgets as widgets

    current = dict(current or control.default_value())
    x_min, x_max = control.value_spec.property("x_range", (0.0, 1.0))
    y_min, y_max = control.value_spec.property("y_range", (0.0, 1.0))
    x_slider = widgets.FloatSlider(
        value=float(current.get("x", x_min)),
        min=float(x_min),
        max=float(x_max),
        description=str(control.value_spec.property("x_label", "X")),
        continuous_update=True,
    )
    y_slider = widgets.FloatSlider(
        value=float(current.get("y", y_min)),
        min=float(y_min),
        max=float(y_max),
        description=str(control.value_spec.property("y_label", "Y")),
        continuous_update=True,
    )

    def emit(_change=None) -> None:
        context.emit({"x": float(x_slider.value), "y": float(y_slider.value)})

    x_slider.observe(emit, names="value")
    y_slider.observe(emit, names="value")
    widget = widgets.VBox(
        [widgets.HTML(value=f"<b>{control.label}</b>"), x_slider, y_slider]
    )

    def set_value(value: Any) -> None:
        resolved = dict(value)
        x_slider.value = float(resolved.get("x", x_slider.value))
        y_slider.value = float(resolved.get("y", y_slider.value))

    return NotebookControlPresentation(widget, set_value)


def _button(
    context: NotebookActionRenderContext,
    action: ActionSpec,
    values: dict[Any, Any],
) -> Any:
    del values
    import ipywidgets as widgets

    tooltip = (
        f"Shortcut: {', '.join(action.shortcuts)}" if action.shortcuts else ""
    )
    widget = widgets.Button(description=action.label, tooltip=tooltip)
    widget.on_click(lambda _button: context.invoke())
    return widget


def register_first_party_notebook_presentations() -> None:
    """Register every notebook-native presentation shipped in the wheel."""
    global _registered
    if _registered:
        return
    register_control_renderer("slider", _slider)
    register_control_renderer("spinbox", _spinbox)
    register_control_renderer("dropdown", _dropdown)
    register_control_renderer("checkbox", _checkbox)
    register_control_renderer("text", _text)
    register_control_renderer("xy_pad", _xy_pad)
    register_action_renderer("button", _button)
    _registered = True


__all__ = ["register_first_party_notebook_presentations"]
