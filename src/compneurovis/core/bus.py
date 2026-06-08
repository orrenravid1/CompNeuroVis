"""The Bus: framework routing infrastructure between peer actors.

Singular abstraction for routing in the framework. The Bus is NOT an Actor:
it does not appear in the user's actor hierarchy and is never type-checked
against. It is framework infrastructure that the orchestrator inserts between
peer actors. Peers see one channel each, emit plain messages, and the Bus
delivers only when an explicit address or explicit route says where to send.

Direction is never inferred from actor role. Any actor can emit any kind of
message, and the Bus delivers it per declared routes, never per "is this peer
a backend."

Routing rules, in priority order:

1. ``RoutedMessage`` envelope: unwrap and deliver the inner message to
   ``payload.target_actor_id``.
2. First matching ``RoutingSpec`` rule: match by intent, registered message
   type name, and optional payload attributes.

There is no fallback. Unrouteable messages are topology configuration errors.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from compneurovis.core.app import RoutingSpec
from compneurovis.core.messages import (
    Message,
    MessagePayload,
    RoutedMessage,
)

if TYPE_CHECKING:
    from compneurovis.core.channel import Channel


class BusRoutingError(RuntimeError):
    """Raised when the Bus cannot route a message without explicit policy."""


class Bus:
    """Routing logic plus ownership of per-peer channels."""

    def __init__(
        self,
        *,
        peer_ids: list[str] | tuple[str, ...],
        bus_channels: "dict[str, Channel]",
        routing: RoutingSpec | None = None,
    ) -> None:
        self._peer_ids: tuple[str, ...] = tuple(peer_ids)
        self._channels = dict(bus_channels)
        self._routing = routing or RoutingSpec()

    def step(self) -> int:
        """One pump cycle. Returns the number of messages delivered."""
        routed = 0
        for source_id, channel in self._channels.items():
            for message in channel.poll():
                for target_id, outgoing in self._route(message, source_id):
                    target_channel = self._channels.get(target_id)
                    if target_channel is not None:
                        target_channel.send(outgoing)
                        routed += 1
        return routed

    def publish(
        self,
        message: Message[MessagePayload],
        *,
        targets: tuple[str, ...] | list[str] | None = None,
    ) -> int:
        """Inject a framework-owned message directly to peers."""

        delivered = 0
        target_ids = tuple(targets) if targets is not None else self._peer_ids
        for target_id in target_ids:
            target_channel = self._channels.get(target_id)
            if target_channel is not None:
                target_channel.send(message)
                delivered += 1
        return delivered

    def _route(
        self,
        message: Message[MessagePayload],
        source_id: str,
    ) -> tuple[tuple[str, Message[MessagePayload]], ...]:
        payload = message.payload

        if isinstance(payload, RoutedMessage):
            return ((payload.target_actor_id, payload.message),)

        for route in self._routing.routes:
            if self._matches(message, route.match):
                return tuple((target, message) for target in route.targets if target != source_id)

        raise BusRoutingError(
            f"Bus cannot route {message.type.name!r} from {source_id!r}. "
            "Declare a RouteSpec or emit a RoutedMessage."
        )

    def _matches(self, message: Message[MessagePayload], match) -> bool:
        if match.intent is not None and message.intent != match.intent:
            return False
        if match.message_type is not None and message.type.name != match.message_type:
            return False
        payload = message.payload
        for name, expected in match.attrs.items():
            if getattr(payload, name, None) != expected:
                return False
        return True

    def close(self) -> None:
        for channel in self._channels.values():
            try:
                channel.close()
            except OSError:
                pass


class BusThread:
    """Daemon thread that pumps a Bus until stopped."""

    def __init__(self, bus: Bus, *, idle_sleep_s: float = 0.001) -> None:
        self._bus = bus
        self._idle_sleep_s = idle_sleep_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True, name="Bus")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._bus.close()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                routed = self._bus.step()
            except (BrokenPipeError, EOFError, OSError):
                break
            if routed == 0:
                time.sleep(self._idle_sleep_s)


@dataclass
class BusFabric:
    """Result of building the Bus topology: peer channels plus the Bus."""

    peer_channels: "dict[str, Channel]"
    bus: Bus


def bus_transport(
    *,
    mode: str = "pipe",
):
    """Build a star topology around a Bus."""

    from compneurovis.transports.inprocess import make_inprocess_pair
    from compneurovis.transports.pipe import make_pipe_pair

    def factory(actors, routing: RoutingSpec | None = None) -> BusFabric:
        peer_channels: "dict[str, Channel]" = {}
        bus_channels: "dict[str, Channel]" = {}
        for actor in actors:
            if mode == "pipe":
                pair = make_pipe_pair(left_name=actor.id, right_name=f"bus<->{actor.id}")
            elif mode == "inprocess":
                pair = make_inprocess_pair(left_name=actor.id, right_name=f"bus<->{actor.id}")
            else:
                raise ValueError(
                    f"Unsupported bus_transport mode {mode!r}. Expected 'pipe' or 'inprocess'."
                )
            peer_channels[actor.id] = pair.left
            bus_channels[actor.id] = pair.right
        bus = Bus(
            peer_ids=[actor.id for actor in actors],
            bus_channels=bus_channels,
            routing=routing,
        )
        return BusFabric(peer_channels=peer_channels, bus=bus)

    return factory


__all__ = ["Bus", "BusFabric", "BusRoutingError", "BusThread", "bus_transport"]
