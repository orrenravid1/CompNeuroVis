"""Public authoring registry for named control kinds."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from compneurovis.backends.interaction import BackendInteractionContext
from compneurovis.core.controls import ControlPresentationSpec, ControlValueSpec
from compneurovis.inline.refs import ControlRef


@dataclass(frozen=True)
class ControlAuthoringContext:
    """Stable declaration surface passed to registered control factories."""

    _source: Any
    panel_id: str

    def control(
        self,
        name: str,
        *,
        label: str,
        value_kind: str,
        default: Any,
        value_properties: Mapping[str, Any] | None = None,
        presentation_kind: str,
        presentation_properties: Mapping[str, Any] | None = None,
        get: Callable[[], Any] | None = None,
        set: Callable[[BackendInteractionContext, Any], None] | None = None,
        send_to_backend: bool | None = None,
        ref_type: type[ControlRef] = ControlRef,
    ) -> ControlRef:
        return self._source._register_control(
            name,
            label=label,
            get=get,
            set=set,
            value_spec=ControlValueSpec(
                kind=value_kind,
                default=default,
                properties=value_properties or {},
            ),
            presentation=ControlPresentationSpec(
                kind=presentation_kind,
                properties=presentation_properties or {},
            ),
            send_to_backend=send_to_backend,
            ref_type=ref_type,
            panel_id=self.panel_id,
        )


ControlAuthoringFactory = Callable[..., ControlRef]
_control_factories: dict[str, ControlAuthoringFactory] = {}


def register_control(
    name: str,
    factory: ControlAuthoringFactory,
    *,
    override: bool = False,
) -> None:
    """Register one named control authoring factory."""
    key = str(name).strip()
    if not key:
        raise ValueError("Control name must be a non-empty string")
    if key.startswith("_"):
        raise ValueError("Control name cannot start with '_'")
    from compneurovis.inline.action_registry import registered_actions

    if key in registered_actions():
        raise ValueError(
            f"controls.{key}(...) is already an action authoring name; "
            "choose another control name"
        )
    from compneurovis.inline.widget_registry import widget_name_taken

    if widget_name_taken(key):
        raise ValueError(
            f"source.{key}(...) is already a widget authoring name; "
            "choose another control name"
        )
    if not callable(factory):
        raise TypeError("Control factory must be callable")
    current = _control_factories.get(key)
    if current is factory:
        return
    if current is not None and not override:
        raise ValueError(
            f"Control authoring kind {key!r} is already registered; "
            "pass override=True only for an intentional replacement"
        )
    _control_factories[key] = factory


def control_factory(name: str) -> ControlAuthoringFactory:
    try:
        return _control_factories[name]
    except KeyError:
        registered = ", ".join(repr(item) for item in sorted(_control_factories))
        suffix = f" Registered controls are {registered}." if registered else ""
        raise AttributeError(f"No control kind {name!r} is registered.{suffix}") from None


def registered_controls() -> tuple[str, ...]:
    return tuple(sorted(_control_factories))


__all__ = [
    "ControlAuthoringContext",
    "ControlAuthoringFactory",
    "control_factory",
    "register_control",
    "registered_controls",
]
