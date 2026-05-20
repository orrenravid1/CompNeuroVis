from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, Literal, TypeVar, cast

import numpy as np

from compneurovis.core.app import AppSpec, PanelSpec

MessageIntent = Literal["command", "update"]
PayloadT = TypeVar("PayloadT", bound="MessagePayload")


@dataclass(frozen=True, slots=True)
class MessageType(Generic[PayloadT]):
    name: str
    payload_type: type[PayloadT]
    allowed_intents: tuple[MessageIntent, ...]

    def validate(self, intent: MessageIntent, payload: PayloadT) -> None:
        if intent not in self.allowed_intents:
            allowed = ", ".join(self.allowed_intents)
            raise ValueError(f"Message type {self.name!r} does not allow {intent!r} intent; allowed: {allowed}")
        if not isinstance(payload, self.payload_type):
            raise TypeError(
                f"Message type {self.name!r} expects payload {self.payload_type.__name__}, "
                f"got {type(payload).__name__}"
            )


@dataclass(frozen=True, slots=True)
class Message(Generic[PayloadT]):
    type: MessageType[PayloadT]
    intent: MessageIntent
    payload: PayloadT


@dataclass(frozen=True, slots=True)
class MessagePayload:
    pass


@dataclass(frozen=True, slots=True)
class CommandPayload(MessagePayload):
    pass


@dataclass(frozen=True, slots=True)
class UpdatePayload(MessagePayload):
    pass


@dataclass(frozen=True, slots=True)
class Reset(CommandPayload):
    pass


@dataclass(frozen=True, slots=True)
class SetControl(CommandPayload):
    control_id: str
    value: Any


@dataclass(frozen=True, slots=True)
class InvokeAction(CommandPayload):
    action_id: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RoutedMessage(MessagePayload):
    target_actor_id: str
    message: Message[MessagePayload]


@dataclass(frozen=True, slots=True)
class KeyPressed(CommandPayload):
    key: str


@dataclass(frozen=True, slots=True)
class EntityClicked(CommandPayload):
    entity_id: str


@dataclass(frozen=True, slots=True)
class CameraCommand(CommandPayload):
    target_id: str
    kind: Literal["orbit", "zoom", "reset"]
    dx: float = 0.0
    dy: float = 0.0
    scale: float = 1.0


@dataclass(frozen=True, slots=True)
class StopBackend(CommandPayload):
    pass


@dataclass(frozen=True, slots=True)
class FieldReplace(UpdatePayload):
    field_id: str
    values: np.ndarray
    coords: dict[str, np.ndarray] | None = None
    attrs_update: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FieldAppend(UpdatePayload):
    field_id: str
    append_dim: str
    values: np.ndarray
    coord_values: np.ndarray
    max_length: int | None = None
    attrs_update: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RenderedFrame(UpdatePayload):
    frame_id: str
    data: bytes
    format: str = "png"
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True, slots=True)
class ViewPatch(UpdatePayload):
    view_id: str
    updates: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class OperatorPatch(UpdatePayload):
    operator_id: str
    updates: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ControlPatch(UpdatePayload):
    control_id: str
    updates: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AppMetadataPatch(UpdatePayload):
    updates: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class BindingValuePatch(UpdatePayload):
    """Patch values in the runtime binding namespace.

    These values feed StateBindingSpec references and view/control refresh
    logic. They are projection inputs, not canonical application state.
    """

    updates: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PanelPatch(UpdatePayload):
    """Surgical update to one panel's contents. Does not affect other panels or data catalogs.

    Fields set to ``None`` are left unchanged. Use an empty tuple to explicitly clear a list.
    Only ``kind="controls"`` panels support ``control_ids`` / ``action_ids`` updates.
    For structural panel changes (kind, camera settings, add/remove panels) use ``LayoutReplace``.
    """

    panel_id: str
    control_ids: tuple[str, ...] | None = None
    action_ids: tuple[str, ...] | None = None
    view_ids: tuple[str, ...] | None = None
    title: str | None = None


@dataclass(frozen=True, slots=True)
class LayoutReplace(UpdatePayload):
    """Replace the full panel arrangement without rebuilding AppSpec data.

    Replaces ``LayoutSpec.panels`` and ``panel_grid`` in actor projections.
    Fields, geometries, views, operators, controls, and actions are untouched.
    Frontends rebuild their widget tree and trigger a full content refresh for
    the new panels.

    Pass ``panel_grid=()`` to use auto-layout.
    """

    panels: tuple[PanelSpec, ...]
    panel_grid: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True, slots=True)
class AppSpecDeclared(UpdatePayload):
    """Declare the immutable startup AppSpec to runtime participants."""

    app_spec: AppSpec


@dataclass(frozen=True, slots=True)
class Status(UpdatePayload):
    message: str
    timeout_ms: int | None = None


@dataclass(frozen=True, slots=True)
class Error(UpdatePayload):
    message: str


def _message_type(
    name: str,
    payload_type: type[PayloadT],
    allowed_intents: tuple[MessageIntent, ...],
) -> MessageType[PayloadT]:
    return MessageType(name=name, payload_type=payload_type, allowed_intents=allowed_intents)


RESET = _message_type("reset", Reset, ("command",))
SET_CONTROL = _message_type("set_control", SetControl, ("command",))
INVOKE_ACTION = _message_type("invoke_action", InvokeAction, ("command",))
ROUTED_MESSAGE = _message_type("routed_message", RoutedMessage, ("command", "update"))
KEY_PRESSED = _message_type("key_pressed", KeyPressed, ("command",))
ENTITY_CLICKED = _message_type("entity_clicked", EntityClicked, ("command",))
CAMERA_COMMAND = _message_type("camera_command", CameraCommand, ("command",))
STOP_BACKEND = _message_type("stop_backend", StopBackend, ("command",))

FIELD_REPLACE = _message_type("field_replace", FieldReplace, ("update",))
FIELD_APPEND = _message_type("field_append", FieldAppend, ("update",))
RENDERED_FRAME = _message_type("rendered_frame", RenderedFrame, ("update",))
VIEW_PATCH = _message_type("view_patch", ViewPatch, ("update",))
OPERATOR_PATCH = _message_type("operator_patch", OperatorPatch, ("update",))
CONTROL_PATCH = _message_type("control_patch", ControlPatch, ("update",))
APP_METADATA_PATCH = _message_type("app_metadata_patch", AppMetadataPatch, ("update",))
BINDING_VALUE_PATCH = _message_type("binding_value_patch", BindingValuePatch, ("update",))
PANEL_PATCH = _message_type("panel_patch", PanelPatch, ("update",))
LAYOUT_REPLACE = _message_type("layout_replace", LayoutReplace, ("update",))
APP_SPEC_DECLARED = _message_type("app_spec_declared", AppSpecDeclared, ("update",))
STATUS = _message_type("status", Status, ("update",))
ERROR = _message_type("error", Error, ("update",))

MESSAGE_TYPES: tuple[MessageType[Any], ...] = (
    RESET,
    SET_CONTROL,
    INVOKE_ACTION,
    ROUTED_MESSAGE,
    KEY_PRESSED,
    ENTITY_CLICKED,
    CAMERA_COMMAND,
    STOP_BACKEND,
    FIELD_REPLACE,
    FIELD_APPEND,
    RENDERED_FRAME,
    VIEW_PATCH,
    OPERATOR_PATCH,
    CONTROL_PATCH,
    APP_METADATA_PATCH,
    BINDING_VALUE_PATCH,
    PANEL_PATCH,
    LAYOUT_REPLACE,
    APP_SPEC_DECLARED,
    STATUS,
    ERROR,
)
MESSAGE_TYPES_BY_NAME: dict[str, MessageType[Any]] = {message_type.name: message_type for message_type in MESSAGE_TYPES}
MESSAGE_TYPES_BY_PAYLOAD: dict[type[Any], MessageType[Any]] = {
    message_type.payload_type: message_type for message_type in MESSAGE_TYPES
}


def message_type_for_payload(payload: PayloadT) -> MessageType[PayloadT]:
    payload_type = type(payload)
    try:
        return cast(MessageType[PayloadT], MESSAGE_TYPES_BY_PAYLOAD[payload_type])
    except KeyError as exc:
        raise ValueError(
            f"No registered message type for payload {payload_type.__name__}. "
            "Pass an explicit MessageType when constructing the message."
        ) from exc


def make_message(
    intent: MessageIntent,
    payload: PayloadT,
    *,
    message_type: MessageType[PayloadT] | None = None,
) -> Message[PayloadT]:
    resolved_type = message_type or message_type_for_payload(payload)
    resolved_type.validate(intent, payload)
    return Message(type=resolved_type, intent=intent, payload=payload)


def command_message(
    payload: CommandPayload,
    *,
    message_type: MessageType[CommandPayload] | None = None,
) -> Message[CommandPayload]:
    return make_message("command", payload, message_type=message_type)


def update_message(
    payload: UpdatePayload,
    *,
    message_type: MessageType[UpdatePayload] | None = None,
) -> Message[UpdatePayload]:
    return make_message("update", payload, message_type=message_type)


CommandMessage = Message[CommandPayload]
UpdateMessage = Message[UpdatePayload]
