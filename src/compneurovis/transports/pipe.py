from __future__ import annotations

import queue
import time
from dataclasses import dataclass
from multiprocessing import Pipe
from multiprocessing.connection import Connection
from typing import Any

from compneurovis.core._perf import perf_log
from compneurovis.core.messages import Error, Message, MessagePayload, update_message

DEFAULT_MAX_PAYLOADS_PER_POLL = 16
DEFAULT_MAX_POLL_DURATION_S = 0.004
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
                        more_pending = self._inbound.poll()
                        break
                    if not self._inbound.poll():
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
    left_inbound, right_outbound = Pipe(duplex=False)
    right_inbound, left_outbound = Pipe(duplex=False)
    return PipeEndpointPair(
        left=PipeEndpoint(inbound=left_inbound, outbound=left_outbound, mode="pipe", name=left_name),
        right=PipeEndpoint(inbound=right_inbound, outbound=right_outbound, mode="pipe", name=right_name),
    )


def pipe_transport(id_a: str, id_b: str):
    """TransportFactory for two actors in separate processes (multiprocessing.Pipe).

    Use when at least one actor runs in a subprocess (e.g., ActorProcess).
    For actors that share a process, use inprocess_transport instead.
    """
    def factory(actors, routing=None):
        del actors, routing
        pair = make_pipe_pair(left_name=id_a, right_name=id_b)
        return {id_a: pair.left, id_b: pair.right}
    return factory


__all__ = ["PipeEndpoint", "PipeEndpointPair", "make_pipe_pair", "pipe_transport"]
