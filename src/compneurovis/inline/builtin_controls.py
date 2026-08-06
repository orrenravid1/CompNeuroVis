"""Built-in controls registered through the public authoring contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Callable

from compneurovis.backends.interaction import BackendInteractionContext
from compneurovis.inline.control_registry import (
    ControlAuthoringContext,
    register_control,
)
from compneurovis.inline.refs import (
    CheckboxRef,
    DropdownRef,
    NumberRef,
    SliderRef,
    TextRef,
    XYPadRef,
)


def _initial(default: Any, get: Callable[[], Any] | None, fallback: Any) -> Any:
    if default is not None:
        return default
    if get is not None:
        return get()
    return fallback


def slider(
    context: ControlAuthoringContext,
    name: str,
    *,
    label: str,
    min: float,
    max: float,
    get: Callable[[], Any] | None = None,
    set: Callable[[BackendInteractionContext, Any], None] | None = None,
    default: float | None = None,
    steps: int = 100,
    scale: str = "linear",
    int: bool = False,
    send_to_backend: bool | None = None,
) -> SliderRef:
    raw = _initial(default, get, min)
    return context.control(
        name,
        label=label,
        value_kind="scalar",
        default=round(float(raw)) if int else float(raw),
        value_properties={"min": min, "max": max, "value_type": "int" if int else "float"},
        presentation_kind="slider",
        presentation_properties={"steps": steps, "scale": scale},
        get=get,
        set=set,
        send_to_backend=send_to_backend,
        ref_type=SliderRef,
    )


def number(
    context: ControlAuthoringContext,
    name: str,
    *,
    label: str,
    min: int,
    max: int,
    get: Callable[[], Any] | None = None,
    set: Callable[[BackendInteractionContext, Any], None] | None = None,
    default: int | None = None,
    send_to_backend: bool | None = None,
) -> NumberRef:
    return context.control(
        name,
        label=label,
        value_kind="scalar",
        default=int(round(float(_initial(default, get, min)))),
        value_properties={"min": min, "max": max, "value_type": "int"},
        presentation_kind="spinbox",
        get=get,
        set=set,
        send_to_backend=send_to_backend,
        ref_type=NumberRef,
    )


def dropdown(
    context: ControlAuthoringContext,
    name: str,
    *,
    label: str,
    options: Sequence[str],
    get: Callable[[], Any] | None = None,
    set: Callable[[BackendInteractionContext, Any], None] | None = None,
    default: str | None = None,
    send_to_backend: bool | None = None,
) -> DropdownRef:
    resolved_options = tuple(str(option) for option in options)
    if not resolved_options:
        raise ValueError("dropdown options cannot be empty")
    return context.control(
        name,
        label=label,
        value_kind="choice",
        default=str(_initial(default, get, resolved_options[0])),
        value_properties={"options": resolved_options},
        presentation_kind="dropdown",
        get=get,
        set=set,
        send_to_backend=send_to_backend,
        ref_type=DropdownRef,
    )


def checkbox(
    context: ControlAuthoringContext,
    name: str,
    *,
    label: str,
    get: Callable[[], Any] | None = None,
    set: Callable[[BackendInteractionContext, Any], None] | None = None,
    default: bool | None = None,
    send_to_backend: bool | None = None,
) -> CheckboxRef:
    return context.control(
        name,
        label=label,
        value_kind="bool",
        default=bool(_initial(default, get, False)),
        presentation_kind="checkbox",
        get=get,
        set=set,
        send_to_backend=send_to_backend,
        ref_type=CheckboxRef,
    )


def text(
    context: ControlAuthoringContext,
    name: str,
    *,
    label: str,
    get: Callable[[], Any] | None = None,
    set: Callable[[BackendInteractionContext, Any], None] | None = None,
    default: str | None = None,
    placeholder: str = "",
    max_length: int | None = None,
    send_to_backend: bool | None = None,
) -> TextRef:
    return context.control(
        name,
        label=label,
        value_kind="text",
        default=str(_initial(default, get, "")),
        value_properties={"placeholder": placeholder, "max_length": max_length},
        presentation_kind="text",
        get=get,
        set=set,
        send_to_backend=send_to_backend,
        ref_type=TextRef,
    )


def xy_pad(
    context: ControlAuthoringContext,
    name: str,
    *,
    label: str,
    x: tuple[str, float, float] = ("X", 0.0, 1.0),
    y: tuple[str, float, float] = ("Y", 0.0, 1.0),
    get: Callable[[], Any] | None = None,
    set: Callable[[BackendInteractionContext, Any], None] | None = None,
    default: Mapping[str, float] | None = None,
    send_to_backend: bool | None = None,
) -> XYPadRef:
    x_label, x_min, x_max = x
    y_label, y_min, y_max = y
    resolved = default if default is not None else (get() if get is not None else None)
    if resolved is None:
        resolved = {"x": (x_min + x_max) / 2.0, "y": (y_min + y_max) / 2.0}
    return context.control(
        name,
        label=label,
        value_kind="xy",
        default=dict(resolved),
        value_properties={
            "x_range": (x_min, x_max),
            "y_range": (y_min, y_max),
            "x_label": x_label,
            "y_label": y_label,
        },
        presentation_kind="xy_pad",
        get=get,
        set=set,
        send_to_backend=send_to_backend,
        ref_type=XYPadRef,
    )


def register_builtin_controls() -> None:
    register_control("slider", slider)
    register_control("number", number)
    register_control("dropdown", dropdown)
    register_control("checkbox", checkbox)
    register_control("text", text)
    register_control("xy_pad", xy_pad)


__all__ = ["register_builtin_controls"]
