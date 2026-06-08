from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, TypeAlias

from compneurovis.core._immutability import FrozenDict
from compneurovis.core.specs import IdentifiedSpec, SpecBase


@dataclass(frozen=True, slots=True)
class ScalarValueSpec(SpecBase):
    default: float | int
    min: float | int | None = None
    max: float | int | None = None
    value_type: Literal["float", "int"] = "float"


@dataclass(frozen=True, slots=True)
class ChoiceValueSpec(SpecBase):
    default: str
    options: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "options", tuple(self.options))


@dataclass(frozen=True, slots=True)
class BoolValueSpec(SpecBase):
    default: bool = False


@dataclass(frozen=True, slots=True)
class XYValueSpec(SpecBase):
    default: Mapping[str, float] = field(default_factory=lambda: FrozenDict({"x": 0.5, "y": 0.5}))
    x_range: tuple[float, float] = (0.0, 1.0)
    y_range: tuple[float, float] = (0.0, 1.0)
    x_label: str = "X"
    y_label: str = "Y"

    def __post_init__(self) -> None:
        object.__setattr__(self, "default", FrozenDict(self.default))
        object.__setattr__(self, "x_range", tuple(self.x_range))
        object.__setattr__(self, "y_range", tuple(self.y_range))

    def default_value(self) -> dict[str, float]:
        return {
            "x": float(self.default.get("x", 0.5)),
            "y": float(self.default.get("y", 0.5)),
        }


ControlValueSpec: TypeAlias = ScalarValueSpec | ChoiceValueSpec | BoolValueSpec | XYValueSpec


@dataclass(frozen=True, slots=True)
class ControlPresentationSpec(SpecBase):
    kind: str | None = None
    steps: int | None = None
    scale: str = "linear"
    shape: str | None = None


@dataclass(frozen=True, slots=True)
class ControlSpec(IdentifiedSpec):
    label: str
    value_spec: ControlValueSpec
    presentation: ControlPresentationSpec | None = None
    state_key: str | None = None
    send_to_backend: bool = False

    def default_value(self) -> Any:
        if isinstance(self.value_spec, XYValueSpec):
            return self.value_spec.default_value()
        return self.value_spec.default

    def resolved_state_key(self) -> str:
        return self.state_key or self.id


@dataclass(frozen=True, slots=True)
class ActionSpec(IdentifiedSpec):
    label: str
    payload: Mapping[str, Any] = field(default_factory=FrozenDict)
    shortcuts: tuple[str, ...] = ()
    selection_mode: bool = False
    selection_payload_key: str = "entity_id"

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", FrozenDict(self.payload))
        object.__setattr__(self, "shortcuts", tuple(self.shortcuts))
