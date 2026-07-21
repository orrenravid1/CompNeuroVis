"""Lightweight references returned by source-level authoring methods."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol

from compneurovis.core.values import ValueBindingSpec


class _TraceHandleBinding(Protocol):
    name: str
    _field_id: str

    def _sample(self) -> None: ...


class _SurfaceHandleBinding(Protocol):
    _field_id: str
    _geometry_id: str
    _view_id: str
    _panel_id: str


class _GridSliceHandleBinding(Protocol):
    _operator_id: str
    _panel_id: str


class _ControlHandleBinding(Protocol):
    name: str
    _control_id: str


class _ActionHandleBinding(Protocol):
    name: str
    shortcuts: tuple[str, ...]


@dataclass(frozen=True)
class DataHandle:
    """Source-agnostic reference to data available to a widget."""

    _field_id: str
    _series_dim: str | None = None
    _selectors: Mapping[str, Any] = field(default_factory=dict)
    _unit: str | None = None


@dataclass(frozen=True, slots=True)
class PanelHandle:
    """Reference to a visible panel accepted by cnv.layout()."""

    id: str


@dataclass(frozen=True, slots=True)
class SelectionRef:
    """Handle to morphology selection state."""

    key: str
    select_multiple: bool = False
    _is_selection_ref: bool = True


@dataclass(frozen=True, slots=True)
class MorphologyHandle(PanelHandle):
    """Handle returned by source.morphology()."""

    selected: SelectionRef
    selection: DataHandle | None = None


@dataclass(frozen=True, slots=True)
class ValueRef:
    """Reference to named runtime state created by source.create_value()."""

    key: str


def binding_key(value: Any) -> str:
    """Resolve an authoring handle to its runtime value key."""
    if isinstance(value, ControlHandle):
        return value.value_key
    if isinstance(value, ValueRef):
        return value.key
    return str(value)


def bind(value: Any) -> Any:
    """Lower inline handles to canonical runtime state bindings."""
    if isinstance(value, (ControlHandle, SelectionRef, ValueRef)):
        return ValueBindingSpec(binding_key(value))
    return value


class SurfaceHandle(PanelHandle):
    """Handle returned by source.surface() and accepted by grid_slice()."""

    __slots__ = ("_binding",)

    def __init__(self, binding: _SurfaceHandleBinding) -> None:
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


class GridSliceHandle(PanelHandle):
    """Handle returned by source.grid_slice()."""

    __slots__ = ("_binding",)

    def __init__(self, binding: _GridSliceHandleBinding) -> None:
        super().__init__(binding._panel_id)
        object.__setattr__(self, "_binding", binding)

    @property
    def operator_id(self) -> str:
        return self._binding._operator_id


class LineHandle(PanelHandle):
    """Uniform handle for sampled and existing-data line plots."""

    __slots__ = ("_binding", "_field_id")

    def __init__(
        self,
        panel_id: str,
        binding: _TraceHandleBinding | None = None,
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
class BarHandle(PanelHandle):
    """Handle returned by source.bar()."""


@dataclass(frozen=True, slots=True)
class Network2DHandle(PanelHandle):
    """Handle returned by source.network2d()."""


class ControlHandle:
    """Reference to a registered control and its runtime value."""

    __slots__ = ("_binding",)

    def __init__(self, binding: _ControlHandleBinding) -> None:
        self._binding = binding

    @property
    def name(self) -> str:
        return self._binding.name

    @property
    def value_key(self) -> str:
        return self._binding._control_id


class SliderHandle(ControlHandle):
    """Handle returned by source.slider()."""


class NumberHandle(ControlHandle):
    """Handle returned by source.number()."""


class DropdownHandle(ControlHandle):
    """Handle returned by source.dropdown()."""


class CheckboxHandle(ControlHandle):
    """Handle returned by source.checkbox()."""


class TextHandle(ControlHandle):
    """Handle returned by source.text()."""


class XYPadHandle(ControlHandle):
    """Handle returned by source.xy_pad()."""


class ActionHandle:
    """Reference to an action created by source.button() or source.hotkey()."""

    __slots__ = ("_binding",)

    def __init__(self, binding: _ActionHandleBinding) -> None:
        self._binding = binding

    @property
    def name(self) -> str:
        return self._binding.name


__all__ = [
    "ActionHandle",
    "BarHandle",
    "CheckboxHandle",
    "ControlHandle",
    "DropdownHandle",
    "DataHandle",
    "GridSliceHandle",
    "LineHandle",
    "MorphologyHandle",
    "NumberHandle",
    "PanelHandle",
    "SelectionRef",
    "SliderHandle",
    "Network2DHandle",
    "SurfaceHandle",
    "TextHandle",
    "ValueRef",
    "XYPadHandle",
    "bind",
    "binding_key",
]
