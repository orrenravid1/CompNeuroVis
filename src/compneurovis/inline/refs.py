"""Lightweight references returned by source-level authoring methods."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from compneurovis.core.values import ValueBindingSpec


class _SeriesRefBinding(Protocol):
    name: str
    _field_id: str

    def _sample(self) -> None: ...


class _SurfaceRefBinding(Protocol):
    _field_id: str
    _geometry_id: str
    _view_id: str
    _panel_id: str


class _ControlRefBinding(Protocol):
    name: str
    _control_id: str


class _ActionRefBinding(Protocol):
    name: str
    shortcuts: tuple[str, ...]


@dataclass(frozen=True)
class DataRef:
    """Source-agnostic reference to data available to a widget."""

    _field_id: str
    _series_dim: str | None = None
    _selectors: Mapping[str, Any] = field(default_factory=dict)
    _unit: str | None = None


@dataclass(frozen=True, slots=True)
class PanelRef:
    """Reference to a visible panel accepted by cnv.layout()."""

    id: str


@dataclass(frozen=True, slots=True)
class SelectionRef:
    """Reference to morphology selection state."""

    key: str
    select_multiple: bool = False
    _is_selection_ref: bool = True


@dataclass(frozen=True, slots=True)
class MorphologyRef(PanelRef):
    """Reference returned by source.morphology()."""

    selected: SelectionRef
    selection: DataRef | None = None


@dataclass(frozen=True, slots=True)
class ValueRef:
    """Reference to named runtime state created by source.create_value()."""

    key: str


def binding_key(value: Any) -> str:
    """Resolve an authoring reference to its runtime value key."""
    if isinstance(value, ControlRef):
        return value.value_key
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

    __slots__ = ("_binding",)

    def __init__(self, binding: _SurfaceRefBinding) -> None:
        super().__init__(binding._panel_id)
        object.__setattr__(self, "_binding", binding)

    @property
    def field_id(self) -> str:
        return self._binding._field_id

    @property
    def geometry_id(self) -> str:
        return self._binding._geometry_id

    @property
    def view_id(self) -> str:
        return self._binding._view_id


class LineRef(PanelRef):
    """Uniform reference for sampled and existing-data line plots."""

    __slots__ = ("_binding", "_field_id")

    def __init__(
        self,
        panel_id: str,
        binding: _SeriesRefBinding | None = None,
        *,
        field_id: str | None = None,
    ) -> None:
        super().__init__(panel_id)
        object.__setattr__(self, "_binding", binding)
        resolved = (
            field_id
            if field_id is not None
            else (binding._field_id if binding is not None else None)
        )
        object.__setattr__(self, "_field_id", resolved)

    @property
    def field_id(self) -> str | None:
        """Data field drawn by this line."""
        return self._field_id

    @property
    def name(self) -> str | None:
        """Trace name, or None for an existing-data line."""
        return None if self._binding is None else self._binding.name

    def sample(self) -> None:
        """Sample a callable-backed line immediately."""
        if self._binding is not None:
            self._binding._sample()


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


__all__ = [
    "ActionRef",
    "BarRef",
    "CheckboxRef",
    "ControlRef",
    "DropdownRef",
    "DataRef",
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
