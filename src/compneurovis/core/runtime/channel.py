from __future__ import annotations

from typing import Protocol, runtime_checkable

from compneurovis.core.messages import Message, MessagePayload


@runtime_checkable
class Channel(Protocol):
    """Message channel consumed by hosts and routing infrastructure."""

    def send(self, message: Message[MessagePayload]) -> None: ...

    def poll(self) -> list[Message[MessagePayload]]: ...

    def close(self) -> None: ...


__all__ = ["Channel"]
