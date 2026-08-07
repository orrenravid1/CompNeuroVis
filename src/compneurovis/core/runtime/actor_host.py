from __future__ import annotations

import threading
import time
from typing import Any, Callable, Protocol, TypeAlias

from compneurovis.core.runtime.actor import ActorBase, ActorSource
from compneurovis.core.app_spec import AppSpec
from compneurovis.core.runtime.channel import Channel
from compneurovis.core.messages import StopActor
from compneurovis.core.runtime.performance import perf_log, perf_logging_enabled


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
        self._perf_window_started = time.monotonic()
        self._perf_step_count = 0
        self._perf_receive_ms = 0.0
        self._perf_tick_ms = 0.0
        self._perf_flush_ms = 0.0
        self._perf_flush_ms_max = 0.0
        self._perf_outbound_count = 0

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

    def flush(self) -> int:
        actor = self._actor()
        messages = actor.take_outbound_messages()
        if self.channel is None:
            return len(messages)
        for message in messages:
            self.channel.send(message)
        return len(messages)

    def step(self) -> None:
        if not perf_logging_enabled():
            self.receive()
            if self.should_stop():
                return
            actor = self._actor()
            if actor.is_active():
                actor.tick()
            self.flush()
            return

        receive_started = time.monotonic()
        self.receive()
        receive_ms = (time.monotonic() - receive_started) * 1000.0
        if self.should_stop():
            return
        actor = self._actor()
        tick_started = time.monotonic()
        if actor.is_active():
            actor.tick()
        tick_ms = (time.monotonic() - tick_started) * 1000.0
        flush_started = time.monotonic()
        outbound_count = self.flush()
        flush_ms = (time.monotonic() - flush_started) * 1000.0
        self._record_perf_step(
            actor=actor,
            receive_ms=receive_ms,
            tick_ms=tick_ms,
            flush_ms=flush_ms,
            outbound_count=outbound_count,
        )

    def _record_perf_step(
        self,
        *,
        actor: ActorBase,
        receive_ms: float,
        tick_ms: float,
        flush_ms: float,
        outbound_count: int,
    ) -> None:
        now = time.monotonic()
        self._perf_step_count += 1
        self._perf_receive_ms += receive_ms
        self._perf_tick_ms += tick_ms
        self._perf_flush_ms += flush_ms
        self._perf_flush_ms_max = max(self._perf_flush_ms_max, flush_ms)
        self._perf_outbound_count += outbound_count
        elapsed_s = now - self._perf_window_started
        if elapsed_s < 1.0:
            return
        step_count = self._perf_step_count
        perf_log(
            "actor_host",
            "step_window",
            actor_type=type(actor).__name__,
            window_s=round(elapsed_s, 3),
            step_count=step_count,
            step_hz=round(step_count / elapsed_s, 3),
            receive_ms_total=round(self._perf_receive_ms, 3),
            tick_ms_total=round(self._perf_tick_ms, 3),
            flush_ms_total=round(self._perf_flush_ms, 3),
            flush_ms_avg=round(self._perf_flush_ms / max(step_count, 1), 3),
            flush_ms_max=round(self._perf_flush_ms_max, 3),
            outbound_count=self._perf_outbound_count,
        )
        self._perf_window_started = now
        self._perf_step_count = 0
        self._perf_receive_ms = 0.0
        self._perf_tick_ms = 0.0
        self._perf_flush_ms = 0.0
        self._perf_flush_ms_max = 0.0
        self._perf_outbound_count = 0

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
