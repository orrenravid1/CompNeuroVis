from __future__ import annotations

import queue
import time
from dataclasses import dataclass
from multiprocessing.connection import Connection
from typing import Any

from compneurovis.core.runtime.performance import perf_log
from compneurovis.core.runtime.process_context import spawn_context
from compneurovis.core.messages import Error, Message, MessagePayload, update_message

DEFAULT_MAX_PAYLOADS_PER_POLL = 16
DEFAULT_MAX_POLL_DURATION_S = 0.004
DEFAULT_MPQUEUE_MAXSIZE = 256
TRANSPORT_POLL_LOG_THRESHOLD_MS = 5.0
TRANSPORT_SEND_LOG_THRESHOLD_MS = 5.0


class PipeEndpoint:
    """One endpoint of a bidirectional local message pipe."""

    def __init__(
        self,
        *,
        inbound: Connection | queue.Queue,
        outbound: Connection | queue.Queue,
        mode: str,
        name: str,
    ) -> None:
        self._inbound = inbound
        self._outbound = outbound
        self.mode = mode
        self.name = name
        self.dead = False
        self.max_payloads_per_poll = DEFAULT_MAX_PAYLOADS_PER_POLL
        self.max_poll_duration_s = DEFAULT_MAX_POLL_DURATION_S
        self.last_payload_count = 0
        self.last_poll_truncated = False
        self.last_more_pending = False
        self.last_poll_duration_ms = 0.0

    def poll(self) -> list[Message[MessagePayload]]:
        started = time.monotonic()
        messages: list[Message[MessagePayload]] = []
        payload_count = 0
        truncated = False
        more_pending = False

        def append_payload(payload: Any) -> None:
            if isinstance(payload, list):
                messages.extend(payload)
            else:
                messages.append(payload)

        if self.mode == "pipe":
            try:
                while not self.dead:
                    if payload_count >= self.max_payloads_per_poll or time.monotonic() - started >= self.max_poll_duration_s:
                        truncated = True
                        more_pending = self._inbound.poll(0.0)
                        break
                    if not self._inbound.poll(0.0):
                        break
                    append_payload(self._inbound.recv())
                    payload_count += 1
            except (BrokenPipeError, EOFError, OSError) as exc:
                self.dead = True
                messages.append(update_message(Error(f"Pipe endpoint {self.name!r} ended unexpectedly: {exc}")))
        else:
            while True:
                if payload_count >= self.max_payloads_per_poll or time.monotonic() - started >= self.max_poll_duration_s:
                    truncated = True
                    more_pending = not self._inbound.empty()
                    break
                try:
                    append_payload(self._inbound.get_nowait())
                    payload_count += 1
                except queue.Empty:
                    break

        self.last_payload_count = payload_count
        self.last_poll_truncated = truncated
        self.last_more_pending = more_pending
        self.last_poll_duration_ms = round((time.monotonic() - started) * 1000.0, 3)
        if (
            payload_count
            or messages
            or truncated
            or more_pending
            or self.last_poll_duration_ms >= TRANSPORT_POLL_LOG_THRESHOLD_MS
        ):
            perf_log(
                "transport",
                "poll",
                endpoint=self.name,
                mode=self.mode,
                payload_count=payload_count,
                message_count=len(messages),
                truncated=truncated,
                more_pending=more_pending,
                duration_ms=self.last_poll_duration_ms,
            )
        return messages

    def send(self, message: Message[MessagePayload]) -> None:
        started = time.monotonic()
        try:
            if self.mode == "pipe":
                self._outbound.send(message)
            elif self.mode == "mpqueue":
                # Field updates are ordered state transitions. Backpressure the
                # producer rather than dropping a snapshot/append and corrupting
                # the consumer's field projection.
                self._outbound.put(message)
            else:
                self._outbound.put(message)
        finally:
            duration_ms = round((time.monotonic() - started) * 1000.0, 3)
            if duration_ms >= TRANSPORT_SEND_LOG_THRESHOLD_MS:
                perf_log(
                    "transport",
                    "send",
                    endpoint=self.name,
                    mode=self.mode,
                    intent=message.intent,
                    message_type=type(message.payload).__name__,
                    duration_ms=duration_ms,
                )

    def close(self) -> None:
        if self.mode == "mpqueue":
            return
        for endpoint in (self._inbound, self._outbound):
            close = getattr(endpoint, "close", None)
            if callable(close):
                try:
                    close()
                except OSError:
                    pass

@dataclass(slots=True)
class PipeEndpointPair:
    left: PipeEndpoint
    right: PipeEndpoint


def make_pipe_pair(*, left_name: str = "left", right_name: str = "right") -> PipeEndpointPair:
    process_context = spawn_context()
    left_inbound, right_outbound = process_context.Pipe(duplex=False)
    right_inbound, left_outbound = process_context.Pipe(duplex=False)
    return PipeEndpointPair(
        left=PipeEndpoint(inbound=left_inbound, outbound=left_outbound, mode="pipe", name=left_name),
        right=PipeEndpoint(inbound=right_inbound, outbound=right_outbound, mode="pipe", name=right_name),
    )




def make_mpqueue_pair(
    *,
    left_name: str = "left",
    right_name: str = "right",
    maxsize: int = DEFAULT_MPQUEUE_MAXSIZE,
) -> PipeEndpointPair:
    process_context = spawn_context()
    left_inbound = process_context.Queue(maxsize=maxsize)
    right_inbound = process_context.Queue(maxsize=maxsize)
    return PipeEndpointPair(
        left=PipeEndpoint(inbound=left_inbound, outbound=right_inbound, mode="mpqueue", name=left_name),
        right=PipeEndpoint(inbound=right_inbound, outbound=left_inbound, mode="mpqueue", name=right_name),
    )

def pipe_transport(id_a: str, id_b: str):
    """Bus transport factory for exactly two actors using multiprocessing pipes.

    Use when at least one actor runs in a subprocess (e.g., ActorProcess).
    For actors that share a process, use inprocess_transport instead.
    """
    def factory(actors, routing=None):
        actor_ids = {actor.id for actor in actors}
        expected = {id_a, id_b}
        if actor_ids != expected:
            raise ValueError(
                f"pipe_transport expected actor ids {sorted(expected)}, "
                f"got {sorted(actor_ids)}"
            )
        from compneurovis.core.runtime.bus import bus_transport

        return bus_transport(mode="pipe")(actors, routing)

    return factory


__all__ = ["PipeEndpoint", "PipeEndpointPair", "make_mpqueue_pair", "make_pipe_pair", "pipe_transport"]
