from __future__ import annotations

import threading
from typing import Any, Callable, Protocol, TypeAlias

from compneurovis.core.runtime.actor import ActorBase, ActorSource
from compneurovis.core.app_spec import AppSpec
from compneurovis.core.runtime.channel import Channel
from compneurovis.core.messages import StopActor


class Startable(Protocol):
    """Uniform lifecycle interface for in-process hosts and subprocess actors."""

    def start(self) -> None: ...
    def run(self) -> None: ...
    def stop(self) -> None: ...


ActorHostSource: TypeAlias = Callable[..., Startable]
TransportFactory: TypeAlias = Callable[..., Any]


def resolve_actor_source(source: ActorSource) -> ActorBase:
    if isinstance(source, type):
        return source()
    if callable(source):
        return source()
    raise TypeError(f"Unsupported actor source: {source!r}")


class ChannelHostBase:
    def __init__(self, channel: Channel | None = None) -> None:
        self.channel = channel
        self._channel_stop_lock = threading.Lock()
        self._channel_stopped = False

    def start(self) -> None:
        pass

    def run(self) -> None:
        pass

    def stop(self) -> None:
        with self._channel_stop_lock:
            if self._channel_stopped:
                return
            self._channel_stopped = True
            channel = self.channel
        if channel is not None:
            channel.close()


class ConnectionSlotHost(ChannelHostBase):
    """Holds a channel open for a remotely-connected actor."""


class ActorHost(ChannelHostBase):
    def __init__(self, channel: Channel | None = None) -> None:
        super().__init__(channel=channel)
        self.actor: ActorBase | None = None
        self._stop_requested = False
        self._actor_stop_lock = threading.Lock()
        self._actor_stopped = False

    def start(self, actor_source: ActorSource, app_spec: AppSpec | None) -> ActorBase:
        self.actor = resolve_actor_source(actor_source)
        self.actor.initialize(app_spec)
        return self.actor

    def receive(self) -> None:
        actor = self._actor()
        if self.channel is None:
            return
        for message in self.channel.poll():
            if isinstance(message.payload, StopActor):
                self._stop_requested = True
                return
            actor.handle(message)

    def flush(self) -> None:
        actor = self._actor()
        if self.channel is None:
            actor.take_outbound_messages()
            return
        for message in actor.take_outbound_messages():
            self.channel.send(message)

    def step(self) -> None:
        self.receive()
        if self.should_stop():
            return
        actor = self._actor()
        if actor.is_active():
            actor.tick()
        self.flush()

    def idle_sleep(self) -> float:
        return self._actor().idle_sleep()

    def should_stop(self) -> bool:
        return self._stop_requested

    def stop(self) -> None:
        with self._actor_stop_lock:
            if self._actor_stopped:
                return
            self._actor_stopped = True
            self._stop_requested = True
            actor = self.actor
        try:
            if actor is not None:
                actor.shutdown()
        finally:
            super().stop()

    def _actor(self) -> ActorBase:
        if self.actor is None:
            raise RuntimeError("ActorHost.start() must be called before stepping.")
        return self.actor


__all__ = [
    "ActorHost",
    "ActorHostSource",
    "ChannelHostBase",
    "ConnectionSlotHost",
    "Startable",
    "TransportFactory",
    "resolve_actor_source",
]
