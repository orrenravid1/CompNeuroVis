from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any, Generic, Literal, Mapping, TypeVar, cast

import numpy as np

from compneurovis.core._immutability import (
    FrozenDict,
    readonly_1d_array,
    readonly_array,
    snapshot_message_data,
)
from compneurovis.core.app_spec import AppSpec, PanelSpec

MessageIntent = Literal["command", "update"]
PayloadT = TypeVar("PayloadT", bound="MessagePayload")


def _rebuild_message_payload(
    payload_type: type["MessagePayload"],
    values: tuple[tuple[str, Any], ...],
) -> "MessagePayload":
    """Re-run payload snapshots and validation after deserialization."""

    return payload_type(**dict(values))


@dataclass(frozen=True, slots=True)
class MessageType(Generic[PayloadT]):
    name: str
    payload_type: type[PayloadT]
    allowed_intents: tuple[MessageIntent, ...]

    def __post_init__(self) -> None:
        name = str(self.name).strip()
        intents = tuple(self.allowed_intents)
        if not name:
            raise ValueError("MessageType.name cannot be empty")
        if not intents:
            raise ValueError("MessageType.allowed_intents cannot be empty")
        invalid = tuple(
            intent for intent in intents if intent not in ("command", "update")
        )
        if invalid:
            raise ValueError(
                f"MessageType.allowed_intents contains invalid values: {invalid!r}"
            )
        if len(set(intents)) != len(intents):
            raise ValueError("MessageType.allowed_intents cannot contain duplicates")
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "allowed_intents", intents)

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
    tags: Mapping[str, Any] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        self.type.validate(self.intent, self.payload)
        object.__setattr__(
            self,
            "tags",
            snapshot_message_data(self.tags, path="Message.tags"),
        )

    def __reduce__(self):
        return (type(self), (self.type, self.intent, self.payload, self.tags))


@dataclass(frozen=True, slots=True)
class MessagePayload:
    def __reduce__(self):
        values = tuple(
            (item.name, getattr(self, item.name))
            for item in fields(self)
            if item.init
        )
        return (_rebuild_message_payload, (type(self), values))


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
class InvokeAction(CommandPayload):
    action_id: str
    payload: Mapping[str, Any] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "payload",
            snapshot_message_data(self.payload, path="InvokeAction.payload"),
        )


@dataclass(frozen=True, slots=True)
class RoutedMessage(MessagePayload):
    target_actor_id: str
    message: Message[MessagePayload]


@dataclass(frozen=True, slots=True)
class KeyPressed(CommandPayload):
    key: str


@dataclass(frozen=True, slots=True)
class EntityClicked(CommandPayload):
    interaction_id: str
    entity_id: str


@dataclass(frozen=True, slots=True)
class CameraCommand(CommandPayload):
    target_id: str
    kind: Literal["orbit", "zoom", "reset"]
    dx: float = 0.0
    dy: float = 0.0
    scale: float = 1.0


@dataclass(frozen=True, slots=True)
class StopActor(CommandPayload):
    pass


@dataclass(frozen=True, slots=True)
class BeginExecution(CommandPayload):
    """Release an initialized actor whose runtime profile gates active ticks."""


@dataclass(frozen=True, slots=True)
class FramePresented(CommandPayload):
    """A raster frame was decoded and painted by its presentation client."""

    frame_id: str
    sequence: int

    def __post_init__(self) -> None:
        frame_id = str(self.frame_id).strip()
        sequence = int(self.sequence)
        if not frame_id:
            raise ValueError("FramePresented.frame_id cannot be empty")
        if sequence < 0:
            raise ValueError("FramePresented.sequence cannot be negative")
        object.__setattr__(self, "frame_id", frame_id)
        object.__setattr__(self, "sequence", sequence)


@dataclass(frozen=True, slots=True)
class FieldReplace(UpdatePayload):
    field_id: str
    values: np.ndarray
    coords: Mapping[str, np.ndarray] | None = None
    attrs_update: Mapping[str, Any] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", readonly_array(self.values))
        if self.coords is not None:
            object.__setattr__(
                self,
                "coords",
                FrozenDict(
                    {
                        str(name): readonly_1d_array(
                            coord,
                            error="FieldReplace coordinates must be one-dimensional",
                        )
                        for name, coord in self.coords.items()
                    }
                ),
            )
        object.__setattr__(
            self,
            "attrs_update",
            snapshot_message_data(
                self.attrs_update, path="FieldReplace.attrs_update"
            ),
        )


@dataclass(frozen=True, slots=True)
class FieldAppend(UpdatePayload):
    field_id: str
    append_dim: str
    values: np.ndarray
    coord_values: np.ndarray
    max_length: int | None = None
    attrs_update: Mapping[str, Any] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", readonly_array(self.values))
        object.__setattr__(
            self,
            "coord_values",
            readonly_1d_array(
                self.coord_values,
                error="FieldAppend coord_values must be one-dimensional",
            ),
        )
        object.__setattr__(
            self,
            "attrs_update",
            snapshot_message_data(
                self.attrs_update, path="FieldAppend.attrs_update"
            ),
        )


@dataclass(frozen=True, slots=True)
class RenderedFrame(UpdatePayload):
    frame_id: str
    data: bytes
    format: str = "png"
    width: int | None = None
    height: int | None = None
    sequence: int = 0

    def __post_init__(self) -> None:
        frame_id = str(self.frame_id).strip()
        sequence = int(self.sequence)
        if not frame_id:
            raise ValueError("RenderedFrame.frame_id cannot be empty")
        if sequence < 0:
            raise ValueError("RenderedFrame.sequence cannot be negative")
        object.__setattr__(self, "frame_id", frame_id)
        object.__setattr__(self, "sequence", sequence)
        object.__setattr__(self, "data", bytes(self.data))


@dataclass(frozen=True, slots=True)
class ViewPatch(UpdatePayload):
    view_id: str
    updates: Mapping[str, Any] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "updates",
            snapshot_message_data(self.updates, path="ViewPatch.updates"),
        )


@dataclass(frozen=True, slots=True)
class OperatorPatch(UpdatePayload):
    operator_id: str
    updates: Mapping[str, Any] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "updates",
            snapshot_message_data(self.updates, path="OperatorPatch.updates"),
        )


@dataclass(frozen=True, slots=True)
class ControlPatch(UpdatePayload):
    control_id: str
    updates: Mapping[str, Any] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "updates",
            snapshot_message_data(self.updates, path="ControlPatch.updates"),
        )


@dataclass(frozen=True, slots=True)
class AppMetadataPatch(UpdatePayload):
    updates: Mapping[str, Any] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "updates",
            snapshot_message_data(self.updates, path="AppMetadataPatch.updates"),
        )



@dataclass(frozen=True, slots=True)
class PanelPatch(UpdatePayload):
    """Surgical update to one panel's contents. Does not affect other panels or data catalogs.

    Fields set to ``None`` are left unchanged. Use an empty tuple to explicitly clear a list.
    Any panel host may own ``control_ids`` / ``action_ids``; the registered lifecycle
    decides how to present them. For structural panel changes (kind, camera
    settings, add/remove panels) use ``LayoutReplace``.
    """

    panel_id: str
    control_ids: tuple[str, ...] | None = None
    action_ids: tuple[str, ...] | None = None
    view_ids: tuple[str, ...] | None = None
    title: str | None = None

    def __post_init__(self) -> None:
        for name in ("control_ids", "action_ids", "view_ids"):
            values = getattr(self, name)
            if values is not None:
                object.__setattr__(self, name, tuple(values))


@dataclass(frozen=True, slots=True)
class LayoutReplace(UpdatePayload):
    """Replace a panel arrangement without rebuilding AppSpec data.

    An untagged message replaces the integrated app-shell layout. A message
    carrying ``tags={"fragment_id": ...}`` replaces only that fragment's local
    layout and reconciles its owned panels into the shell. Other fragments are
    left intact. Fields, geometries, views, operators, controls, and actions are
    untouched.
    """

    panels: tuple[PanelSpec, ...]
    panel_grid: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        panels = tuple(self.panels)
        if any(type(panel) is not PanelSpec for panel in panels):
            raise TypeError(
                "LayoutReplace.panels must contain only core PanelSpec values"
            )
        object.__setattr__(self, "panels", panels)
        object.__setattr__(
            self,
            "panel_grid",
            tuple(tuple(row) for row in self.panel_grid),
        )


@dataclass(frozen=True, slots=True)
class AppSpecDeclared(UpdatePayload):
    """Declare the immutable startup AppSpec to runtime participants."""

    app_spec: AppSpec

    def __post_init__(self) -> None:
        if type(self.app_spec) is not AppSpec:
            raise TypeError(
                "AppSpecDeclared.app_spec must be the core AppSpec envelope"
            )


@dataclass(frozen=True, slots=True)
class Status(UpdatePayload):
    message: str
    timeout_ms: int | None = None


@dataclass(frozen=True, slots=True)
class Error(UpdatePayload):
    message: str


@dataclass(frozen=True, slots=True)
class ValueChange(MessagePayload):
    """A keyed value change -- the symmetric value message.

    Usable as a ``command`` ("please set these keys") or an ``update`` ("these
    keys are now these values"), so any actor may emit it and any actor may react
    to the keys it holds handlers for. A single change is a one-entry ``updates``.
    """

    updates: Mapping[str, Any] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "updates",
            snapshot_message_data(self.updates, path="ValueChange.updates"),
        )


def _message_type(
    name: str,
    payload_type: type[PayloadT],
    allowed_intents: tuple[MessageIntent, ...],
) -> MessageType[PayloadT]:
    return MessageType(name=name, payload_type=payload_type, allowed_intents=allowed_intents)


RESET = _message_type("reset", Reset, ("command",))
INVOKE_ACTION = _message_type("invoke_action", InvokeAction, ("command",))
ROUTED_MESSAGE = _message_type("routed_message", RoutedMessage, ("command", "update"))
KEY_PRESSED = _message_type("key_pressed", KeyPressed, ("command",))
ENTITY_CLICKED = _message_type("entity_clicked", EntityClicked, ("command",))
CAMERA_COMMAND = _message_type("camera_command", CameraCommand, ("command",))
STOP_ACTOR = _message_type("stop_actor", StopActor, ("command",))
BEGIN_EXECUTION = _message_type("begin_execution", BeginExecution, ("command",))
FRAME_PRESENTED = _message_type("frame_presented", FramePresented, ("command",))

FIELD_REPLACE = _message_type("field_replace", FieldReplace, ("update",))
FIELD_APPEND = _message_type("field_append", FieldAppend, ("update",))
RENDERED_FRAME = _message_type("rendered_frame", RenderedFrame, ("update",))
VIEW_PATCH = _message_type("view_patch", ViewPatch, ("update",))
OPERATOR_PATCH = _message_type("operator_patch", OperatorPatch, ("update",))
CONTROL_PATCH = _message_type("control_patch", ControlPatch, ("update",))
APP_METADATA_PATCH = _message_type("app_metadata_patch", AppMetadataPatch, ("update",))
PANEL_PATCH = _message_type("panel_patch", PanelPatch, ("update",))
LAYOUT_REPLACE = _message_type("layout_replace", LayoutReplace, ("update",))
APP_SPEC_DECLARED = _message_type("app_spec_declared", AppSpecDeclared, ("update",))
STATUS = _message_type("status", Status, ("update",))
ERROR = _message_type("error", Error, ("update",))
VALUE_CHANGE = _message_type("value_change", ValueChange, ("command", "update"))

MESSAGE_TYPES: tuple[MessageType[Any], ...] = (
    RESET,
    INVOKE_ACTION,
    ROUTED_MESSAGE,
    KEY_PRESSED,
    ENTITY_CLICKED,
    CAMERA_COMMAND,
    STOP_ACTOR,
    BEGIN_EXECUTION,
    FRAME_PRESENTED,
    FIELD_REPLACE,
    FIELD_APPEND,
    RENDERED_FRAME,
    VIEW_PATCH,
    OPERATOR_PATCH,
    CONTROL_PATCH,
    APP_METADATA_PATCH,
    PANEL_PATCH,
    LAYOUT_REPLACE,
    APP_SPEC_DECLARED,
    STATUS,
    ERROR,
    VALUE_CHANGE,
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
    tags: Mapping[str, Any] | None = None,
) -> Message[PayloadT]:
    resolved_type = message_type or message_type_for_payload(payload)
    resolved_type.validate(intent, payload)
    return Message(type=resolved_type, intent=intent, payload=payload, tags={} if tags is None else tags)


def command_message(
    payload: MessagePayload,
    *,
    message_type: MessageType[MessagePayload] | None = None,
    tags: Mapping[str, Any] | None = None,
) -> Message[MessagePayload]:
    return make_message("command", payload, message_type=message_type, tags=tags)


def update_message(
    payload: MessagePayload,
    *,
    message_type: MessageType[MessagePayload] | None = None,
    tags: Mapping[str, Any] | None = None,
) -> Message[MessagePayload]:
    return make_message("update", payload, message_type=message_type, tags=tags)


CommandMessage = Message[MessagePayload]
UpdateMessage = Message[MessagePayload]
