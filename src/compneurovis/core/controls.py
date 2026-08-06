"""Neutral control and action declarations.

Control semantics and presentation are kind-keyed data envelopes. Concrete
authoring helpers and frontend renderers register outside core.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from compneurovis.core._immutability import FrozenDict, freeze_spec_data
from compneurovis.core.specs import IdentifiedSpec, SpecBase


@dataclass(frozen=True, slots=True)
class ControlValueSpec(SpecBase):
    """Language-neutral value contract for one registered control kind."""

    kind: str
    default: Any
    properties: Mapping[str, Any] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        kind = str(self.kind).strip()
        if not kind:
            raise ValueError("Control value kind must be a non-empty string")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self, "default", freeze_spec_data(self.default, path="control.default")
        )
        object.__setattr__(
            self,
            "properties",
            freeze_spec_data(self.properties, path="control.properties"),
        )

    def property(self, name: str, default: Any = None) -> Any:
        return self.properties.get(name, default)


@dataclass(frozen=True, slots=True)
class ControlPresentationSpec(SpecBase):
    """Frontend renderer key plus language-neutral renderer properties."""

    kind: str
    properties: Mapping[str, Any] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        kind = str(self.kind).strip()
        if not kind:
            raise ValueError("Control presentation kind must be a non-empty string")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(
            self,
            "properties",
            freeze_spec_data(
                self.properties, path="control.presentation.properties"
            ),
        )

    def property(self, name: str, default: Any = None) -> Any:
        return self.properties.get(name, default)


@dataclass(frozen=True, slots=True)
class ControlSpec(IdentifiedSpec):
    label: str
    value_spec: ControlValueSpec
    presentation: ControlPresentationSpec
    value_key: str | None = None
    send_to_backend: bool = False

    def default_value(self) -> Any:
        default = self.value_spec.default
        return dict(default) if isinstance(default, Mapping) else default

    def resolved_value_key(self) -> str:
        return self.value_key or self.id


@dataclass(frozen=True, slots=True)
class ActionSpec(IdentifiedSpec):
    label: str
    payload: Mapping[str, Any] = field(default_factory=FrozenDict)
    shortcuts: tuple[str, ...] = ()
    selection_mode: bool = False
    selection_payload_key: str = "entity_id"
    presentation_kind: str = "button"
    presentation: Mapping[str, Any] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", FrozenDict(self.payload))
        object.__setattr__(self, "shortcuts", tuple(self.shortcuts))
        object.__setattr__(
            self,
            "presentation",
            freeze_spec_data(self.presentation, path="action.presentation"),
        )
