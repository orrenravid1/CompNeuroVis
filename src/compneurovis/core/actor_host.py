from __future__ import annotations

from typing import Any, Callable, Protocol, TypeAlias

from compneurovis.core._perf import clear_perf_logging_configuration, configure_perf_logging
from compneurovis.core.actor import ActorBase, ActorSource
from compneurovis.core.app import AppSpec, DiagnosticsSpec
from compneurovis.core.channel import Channel
from compneurovis.core.messages import StopActor


class Startable(Protocol):
    """Uniform lifecycle interface for in-process hosts and subprocess actors."""

    def start(self) -> None: ...
    def run(self) -> None: ...
    def stop(self) -> None: ...


ActorHostSource: TypeAlias = Callable[..., Startable]
TransportFactory: TypeAlias = Callable[..., Any]


def resolve_interaction_target_source(source: Any | None) -> Any | None:
    if source is None:
        return None
    if isinstance(source, type):
        return source()
    if callable(source) and not any(hasattr(source, attr) for attr in ("on_action", "on_key_press", "on_entity_clicked")):
        return source()
    return source


def resolve_actor_source(source: ActorSource) -> ActorBase:
    if isinstance(source, type):
        return source()
    if callable(source):
        return source()
    raise TypeError(f"Unsupported actor source: {source!r}")


def configure_diagnostics(diagnostics: DiagnosticsSpec | None) -> None:
    if diagnostics is None:
        clear_perf_logging_configuration()
    else:
        configure_perf_logging(diagnostics)


class ConnectionSlotHost:
    """Holds a channel open for a remotely-connected actor."""

    def __init__(self, channel: Channel | None = None) -> None:
        self.channel = channel

    def start(self) -> None:
        pass

    def run(self) -> None:
        pass

    def stop(self) -> None:
        if self.channel is not None:
            self.channel.close()


class ActorHost:
    def __init__(self, channel: Channel | None = None) -> None:
        self.channel = channel
        self.actor: ActorBase | None = None
        self._stop_requested = False

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
        self._stop_requested = True
        if self.actor is not None:
            self.actor.shutdown()
        if self.channel is not None:
            self.channel.close()

    def _actor(self) -> ActorBase:
        if self.actor is None:
            raise RuntimeError("ActorHost.start() must be called before stepping.")
        return self.actor


__all__ = [
    "ActorHost",
    "ActorHostSource",
    "ConnectionSlotHost",
    "Startable",
    "TransportFactory",
    "configure_diagnostics",
    "resolve_actor_source",
    "resolve_interaction_target_source",
]
