from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any, Callable, Deque, Mapping, TypeAlias

# ActorBase is intentionally NOT ABC: some actors co-inherit from external UI
# classes with metaclasses that conflict with ABCMeta.

if TYPE_CHECKING:
    from compneurovis.core.app_spec import AppSpec
    from compneurovis.core.messages import Message, MessagePayload


_MISSING = object()


class ValueBindings:
    """Per-actor registry of value keys -> handlers, getters, and last values."""

    def __init__(self) -> None:
        self._handlers: dict[Any, Callable[[Any, Any], Any]] = {}
        self._getters: dict[Any, Callable[[], Any]] = {}
        self._values: dict[Any, Any] = {}

    def bind(
        self,
        key: Any,
        handler: Callable[[Any, Any], Any] | None = None,
        *,
        get: Callable[[], Any] | None = None,
        initial: Any = _MISSING,
    ) -> None:
        if handler is not None:
            self._handlers[key] = handler
        if get is not None:
            self._getters[key] = get
        if initial is not _MISSING:
            self._values[key] = initial

    def handles(self, key: Any) -> bool:
        return key in self._handlers

    def set(self, key: Any, value: Any) -> None:
        self._values[key] = value

    def get(self, key: Any, default: Any = None) -> Any:
        getter = self._getters.get(key)
        if getter is not None:
            return getter()
        return self._values.get(key, default)

    def snapshot(self) -> dict[Any, Any]:
        values = dict(self._values)
        for key, getter in self._getters.items():
            values[key] = getter()
        return values

    def apply(self, actor: Any, updates: Mapping[Any, Any]) -> list[Any]:
        """Record each keyed value and run its handler if one is bound."""
        acted: list[Any] = []
        for key, value in updates.items():
            self._values[key] = value
            handler = self._handlers.get(key)
            if handler is not None:
                handler(actor, value)
                acted.append(key)
        return acted


class ActorBase:
    def __init__(self) -> None:
        self._outbound_messages: Deque[Message[MessagePayload]] = deque()
        self.values = ValueBindings()

    def initialize(self, app_spec: AppSpec | None) -> None:
        pass

    def handle(self, message: Message[MessagePayload]) -> None:
        raise NotImplementedError

    def tick(self) -> None:
        pass

    def is_active(self) -> bool:
        return False

    def idle_sleep(self) -> float:
        return 1.0 / 60.0

    def emit(self, message: Message[MessagePayload]) -> None:
        self._outbound_messages.append(message)

    def emit_update(self, update: MessagePayload) -> None:
        from compneurovis.core.messages import update_message
        self.emit(update_message(update))

    def emit_command(self, command: MessagePayload) -> None:
        from compneurovis.core.messages import command_message
        self.emit(command_message(command))

    # Routed-emit helpers: any actor may address a specific peer by id. The Bus
    # reads the RoutedMessage envelope and delivers the inner message to that
    # peer. Direction is preserved by the carrier intent mirroring the inner
    # message intent.

    def emit_routed(self, target_actor_id: str, message: Message[MessagePayload]) -> None:
        from compneurovis.core.messages import ROUTED_MESSAGE, RoutedMessage, make_message
        self.emit(make_message(
            message.intent,
            RoutedMessage(target_actor_id=target_actor_id, message=message),
            message_type=ROUTED_MESSAGE,
        ))

    def emit_command_routed(self, target_actor_id: str, command: MessagePayload) -> None:
        from compneurovis.core.messages import command_message
        self.emit_routed(target_actor_id, command_message(command))

    def emit_update_routed(self, target_actor_id: str, update: MessagePayload) -> None:
        from compneurovis.core.messages import update_message
        self.emit_routed(target_actor_id, update_message(update))

    def take_outbound_messages(self) -> list[Message[MessagePayload]]:
        messages = list(self._outbound_messages)
        self._outbound_messages.clear()
        return messages

    def shutdown(self) -> None:
        pass


class ActorInstanceSource:
    def __init__(self, actor: ActorBase) -> None:
        self._actor = actor

    def __call__(self) -> ActorBase:
        return self._actor


ActorSource: TypeAlias = type[ActorBase] | Callable[[], ActorBase]