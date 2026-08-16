"""Neutral control and action declarations.

Control semantics and presentation are kind-keyed data envelopes. Concrete
authoring helpers and frontend renderers register outside core.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from compneurovis.core._immutability import FrozenDict, freeze_spec_data
from compneurovis.core.keyboard import parse_shortcut
from compneurovis.core.references import validate_local_id
from compneurovis.core.specs import IdentifiedSpec, SpecBase
from compneurovis.core.values import freeze_binding_data


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
        # Binding-capable: a kind's value contract may reference other values,
        # the way an invocation payload does. Non-binding data freezes exactly as
        # before, so this only widens what a value kind may declare.
        object.__setattr__(
            self,
            "properties",
            freeze_binding_data(self.properties, path="control.properties"),
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
    visible: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "visible", bool(self.visible))
        if type(self.value_spec) is not ControlValueSpec:
            raise TypeError(
                "ControlSpec.value_spec must be the core ControlValueSpec envelope"
            )
        if type(self.presentation) is not ControlPresentationSpec:
            raise TypeError(
                "ControlSpec.presentation must be the core "
                "ControlPresentationSpec envelope"
            )
        if self.value_key is not None:
            object.__setattr__(
                self,
                "value_key",
                validate_local_id(
                    self.value_key,
                    path=f"ControlSpec[{self.id!r}].value_key",
                ),
            )

    def default_value(self) -> Any:
        default = self.value_spec.default
        return dict(default) if isinstance(default, Mapping) else default

    def resolved_value_key(self) -> str:
        return self.value_key or self.id


@dataclass(frozen=True, slots=True)
class KeyBindingSpec(IdentifiedSpec):
    """A keyboard shortcut that invokes one scoped interaction.

    A frontend recognizes shortcuts against its own focus and derives a scoped
    semantic invocation of ``invokes``; the handler itself stays in the
    authoritative backend actor and never enters this spec. A binding is not a
    panel item: it has no label, no presentation, and nothing to render, so
    hiding a control never disables a shortcut that targets it.
    """

    shortcuts: tuple[str, ...]
    invokes: str
    payload: Mapping[str, Any] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        shortcuts = tuple(str(shortcut).strip() for shortcut in self.shortcuts)
        if not shortcuts:
            raise ValueError(
                f"KeyBindingSpec[{self.id!r}].shortcuts cannot be empty"
            )
        for shortcut in shortcuts:
            parse_shortcut(shortcut)
        object.__setattr__(self, "shortcuts", shortcuts)
        object.__setattr__(
            self,
            "invokes",
            validate_local_id(
                self.invokes,
                path=f"KeyBindingSpec[{self.id!r}].invokes",
            ),
        )
        object.__setattr__(
            self,
            "payload",
            freeze_binding_data(self.payload, path="key_binding.payload"),
        )


@dataclass(frozen=True, slots=True)
class ActionSpec(IdentifiedSpec):
    label: str
    payload: Mapping[str, Any] = field(default_factory=FrozenDict)
    shortcuts: tuple[str, ...] = ()
    presentation_kind: str = "button"
    presentation: Mapping[str, Any] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        presentation_kind = str(self.presentation_kind).strip()
        if not presentation_kind:
            raise ValueError("ActionSpec.presentation_kind cannot be empty")
        object.__setattr__(self, "presentation_kind", presentation_kind)
        object.__setattr__(
            self,
            "payload",
            freeze_binding_data(self.payload, path="action.payload"),
        )
        shortcuts = tuple(str(shortcut).strip() for shortcut in self.shortcuts)
        for shortcut in shortcuts:
            parse_shortcut(shortcut)
        object.__setattr__(self, "shortcuts", shortcuts)
        object.__setattr__(
            self,
            "presentation",
            freeze_spec_data(self.presentation, path="action.presentation"),
        )
