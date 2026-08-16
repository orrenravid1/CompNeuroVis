"""Lightweight references returned by source-level authoring methods."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

from compneurovis.core._immutability import FrozenDict, readonly_array
from compneurovis.core.references import AppRef
from compneurovis.core.values import ValueBindingSpec


class _ControlRefBinding(Protocol):
    name: str
    _control_id: str


class _ActionRefBinding(Protocol):
    name: str
    shortcuts: tuple[str, ...]


def _freeze_selector(value: Any) -> Any:
    """Own selector data and lower Python-only slices to canonical mappings."""
    if isinstance(value, np.ndarray):
        if value.dtype.hasobject:
            return _freeze_selector(value.tolist())
        return readonly_array(value)
    if isinstance(value, (ValueBindingSpec, AppRef)):
        return value
    if isinstance(value, Mapping):
        return FrozenDict(
            (key, _freeze_selector(item)) for key, item in value.items()
        )
    if isinstance(value, (tuple, list)):
        return tuple(_freeze_selector(item) for item in value)
    if isinstance(value, slice):
        return FrozenDict(
            {
                "kind": "slice",
                "start": _freeze_selector(value.start),
                "stop": _freeze_selector(value.stop),
                "step": _freeze_selector(value.step),
            }
        )
    if isinstance(value, np.generic):
        return _freeze_selector(value.item())
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(
        "Data selectors must contain only scalar values, slices, arrays, "
        "sequences, mappings, or value bindings; "
        f"got {type(value).__module__}.{type(value).__qualname__}"
    )


@dataclass(frozen=True)
class DataRef:
    """Source-agnostic reference to data available to a widget."""

    _field_id: str
    _series_dim: str | None = None
    _selectors: Mapping[str, Any] = field(default_factory=dict)
    _unit: str | None = None

    def __post_init__(self) -> None:
        invalid_dims = tuple(
            dim
            for dim in self._selectors
            if not isinstance(dim, str) or not dim.strip()
        )
        if invalid_dims:
            raise TypeError("DataRef selector dimensions must be non-empty strings")
        object.__setattr__(
            self,
            "_selectors",
            FrozenDict(
                (dim, _freeze_selector(selector))
                for dim, selector in self._selectors.items()
            ),
        )


@dataclass(frozen=True, slots=True)
class GeometryRef:
    """Reference to immutable geometry declared through a widget context."""

    id: str
    kind: str


@dataclass(frozen=True, slots=True)
class PanelRef:
    """Reference to a visible panel accepted by cnv.layout()."""

    id: str


@dataclass(frozen=True, slots=True)
class SelectionRef:
    """Reference to fragment-scoped entity-selection state."""

    id: str
    multiple: bool = False
    _is_selection_ref: bool = True


@dataclass(frozen=True, slots=True)
class EntityClickRef:
    """Reference to an authored geometry-scoped click interaction."""

    id: str


class ControlsRef(PanelRef):
    """Ordinary controls-panel widget with explicitly owned typed controls."""

    __slots__ = ("_source",)

    def __init__(self, panel_id: str, source: Any) -> None:
        super().__init__(panel_id)
        object.__setattr__(self, "_source", source)

    def _call(self, method: str, *args: Any, **kwargs: Any):
        return self._source._invoke_control_factory(
            self.id, method, *args, **kwargs
        )

    def __getattr__(self, name: str):
        from compneurovis.inline.control_registry import registered_controls
        from compneurovis.inline.action_registry import registered_actions

        if name in registered_controls():
            return lambda *args, **kwargs: self._call(name, *args, **kwargs)
        if name in registered_actions():
            return lambda *args, **kwargs: self._source._invoke_action_factory(
                self.id, name, *args, **kwargs
            )
        raise AttributeError(f"{type(self).__name__!s} has no attribute {name!r}")

    def __dir__(self):
        from compneurovis.inline.action_registry import registered_actions
        from compneurovis.inline.control_registry import registered_controls

        return sorted(
            set(super().__dir__())
            | set(registered_controls())
            | set(registered_actions())
        )

    def slider(self, *args: Any, **kwargs: Any):
        return self._call("slider", *args, **kwargs)

    def number(self, *args: Any, **kwargs: Any):
        return self._call("number", *args, **kwargs)

    def dropdown(self, *args: Any, **kwargs: Any):
        return self._call("dropdown", *args, **kwargs)

    def checkbox(self, *args: Any, **kwargs: Any):
        return self._call("checkbox", *args, **kwargs)

    def text(self, *args: Any, **kwargs: Any):
        return self._call("text", *args, **kwargs)

    def xy_pad(self, *args: Any, **kwargs: Any):
        return self._call("xy_pad", *args, **kwargs)

    def button(self, *args: Any, **kwargs: Any) -> "ButtonRef":
        return self._source._call_in_controls_panel(
            self.id, "button", *args, **kwargs
        )

    def hotkey(self, *args: Any, **kwargs: Any) -> "ActionRef":
        return self._source._call_in_controls_panel(
            self.id, "hotkey", *args, **kwargs
        )


@dataclass(frozen=True, slots=True)
class MorphologyRef(PanelRef):
    """Reference returned by source.morphology()."""

    selected: SelectionRef
    entity_click: EntityClickRef | None = None
    selection: DataRef | None = None


@dataclass(frozen=True, slots=True)
class ValueRef:
    """Reference to named runtime state created by source.create_value()."""

    key: str


def binding_key(value: Any) -> str:
    """Resolve an authoring reference to its runtime value key."""
    if isinstance(value, ControlRef):
        return value.value_key
    if isinstance(value, SelectionRef):
        return value.id
    if isinstance(value, ValueRef):
        return value.key
    return str(value)


def bind(value: Any) -> Any:
    """Lower inline references to canonical runtime state bindings."""
    if isinstance(value, (ControlRef, SelectionRef, ValueRef)):
        return ValueBindingSpec(binding_key(value))
    return value


class SurfaceRef(PanelRef):
    """Reference returned by source.surface() and accepted by grid_slice()."""

    __slots__ = ("_field_id",)

    def __init__(self, panel_id: str, field_id: str) -> None:
        super().__init__(panel_id)
        object.__setattr__(self, "_field_id", field_id)

    @property
    def field_id(self) -> str:
        return self._field_id


class LineRef(PanelRef):
    """Uniform reference for sampled and existing-data line plots."""

    __slots__ = ("_field_id",)

    def __init__(
        self,
        panel_id: str,
        *,
        field_id: str | None = None,
    ) -> None:
        super().__init__(panel_id)
        object.__setattr__(self, "_field_id", field_id)

    @property
    def field_id(self) -> str | None:
        """Data field drawn by this line."""
        return self._field_id


@dataclass(frozen=True, slots=True)
class BarRef(PanelRef):
    """Reference returned by source.bar()."""


@dataclass(frozen=True, slots=True)
class Network2DRef(PanelRef):
    """Reference returned by source.network2d()."""


class ControlRef:
    """Reference to a registered control and its runtime value."""

    __slots__ = ("_binding",)

    def __init__(self, binding: _ControlRefBinding) -> None:
        self._binding = binding

    @property
    def name(self) -> str:
        return self._binding.name

    @property
    def value_key(self) -> str:
        return self._binding._control_id


class SliderRef(ControlRef):
    """Reference returned by source.slider()."""


class NumberRef(ControlRef):
    """Reference returned by source.number()."""


class DropdownRef(ControlRef):
    """Reference returned by source.dropdown()."""


class CheckboxRef(ControlRef):
    """Reference returned by source.checkbox()."""


class TextRef(ControlRef):
    """Reference returned by source.text()."""


class XYPadRef(ControlRef):
    """Reference returned by source.xy_pad()."""


class ActionRef:
    """Reference to an action created by source.button() or source.hotkey()."""

    __slots__ = ("_binding",)

    def __init__(self, binding: _ActionRefBinding) -> None:
        self._binding = binding

    @property
    def name(self) -> str:
        return self._binding.name


class ButtonRef(ActionRef):
    """Reference returned by a visible button action."""


class HotkeyRef(ActionRef):
    """Reference returned by a keyboard-only action."""


__all__ = [
    "ActionRef",
    "ButtonRef",
    "BarRef",
    "CheckboxRef",
    "ControlRef",
    "ControlsRef",
    "DropdownRef",
    "DataRef",
    "EntityClickRef",
    "GeometryRef",
    "HotkeyRef",
    "LineRef",
    "MorphologyRef",
    "NumberRef",
    "PanelRef",
    "SelectionRef",
    "SliderRef",
    "Network2DRef",
    "SurfaceRef",
    "TextRef",
    "ValueRef",
    "XYPadRef",
    "bind",
    "binding_key",
]
