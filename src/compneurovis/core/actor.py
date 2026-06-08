from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Callable, Deque, TypeAlias

# ActorBase is intentionally NOT ABC: some actors co-inherit from external UI
# classes with metaclasses that conflict with ABCMeta.

if TYPE_CHECKING:
    from compneurovis.core.app_spec import AppSpec
    from compneurovis.core.messages import CommandPayload, Message, MessagePayload, UpdatePayload


class ActorBase:
    def __init__(self) -> None:
        self._outbound_messages: Deque[Message[MessagePayload]] = deque()

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

    def emit_update(self, update: UpdatePayload) -> None:
        from compneurovis.core.messages import update_message
        self.emit(update_message(update))

    def emit_command(self, command: CommandPayload) -> None:
        from compneurovis.core.messages import command_message
        self.emit(command_message(command))

    # Routed-emit helpers — any actor may address a specific peer by id. The
    # Bus reads the RoutedMessage envelope and delivers the inner message to
    # that peer. Direction (command/update) is preserved by the carrier intent
    # mirroring the inner message's intent.

    def emit_routed(self, target_actor_id: str, message: "Message[MessagePayload]") -> None:
        from compneurovis.core.messages import ROUTED_MESSAGE, RoutedMessage, make_message
        self.emit(make_message(
            message.intent,
            RoutedMessage(target_actor_id=target_actor_id, message=message),
            message_type=ROUTED_MESSAGE,
        ))

    def emit_command_routed(self, target_actor_id: str, command: CommandPayload) -> None:
        from compneurovis.core.messages import command_message
        self.emit_routed(target_actor_id, command_message(command))

    def emit_update_routed(self, target_actor_id: str, update: UpdatePayload) -> None:
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
