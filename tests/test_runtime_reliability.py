from __future__ import annotations

import queue
import threading
import time

import numpy as np
import pytest

from compneurovis.core.messages import (
    Error,
    FieldAppend,
    FieldReplace,
    Reset,
    RoutedMessage,
    command_message,
    update_message,
)
from compneurovis.core.run_spec import (
    ActorSpec,
    MessageMatch,
    RouteSpec,
    RoutingSpec,
    RunSpec,
)
from compneurovis.core.runtime.actor_launchers import (
    ThreadActorLauncher,
    _script_actor_worker,
)
from compneurovis.core.runtime.actor import ActorBase
from compneurovis.core.runtime.app import AppRuntime
from compneurovis.core.runtime.app_handle import AppHandle
from compneurovis.core.runtime.bus import Bus, BusRoutingError, BusThread
from compneurovis.core.runtime.run import run_actor, run_orchestrator
from compneurovis.transports.pipe import PipeEndpoint


class _RecordingChannel:
    def __init__(self) -> None:
        self.messages = []
        self.closed = False

    def send(self, message) -> None:
        self.messages.append(message)

    def poll(self):
        return []

    def close(self) -> None:
        self.closed = True


def _transport_stub(actors, routing):
    del actors, routing
    return None


def test_run_spec_rejects_duplicate_actor_ids() -> None:
    with pytest.raises(ValueError, match="must be unique"):
        RunSpec(
            actors=(ActorSpec(id="worker"), ActorSpec(id="worker")),
            transport=_transport_stub,
        )


def test_run_spec_rejects_non_string_actor_ids() -> None:
    with pytest.raises(TypeError, match="actor ids must be strings"):
        RunSpec(
            actors=(ActorSpec(id=1),),
            transport=_transport_stub,
        )


def test_run_spec_rejects_unknown_route_targets() -> None:
    with pytest.raises(ValueError, match="unknown actor ids: missing"):
        RunSpec(
            actors=(ActorSpec(id="worker"),),
            transport=_transport_stub,
            routing=RoutingSpec(
                routes=(
                    RouteSpec(
                        match=MessageMatch(intent="update"),
                        targets=("missing",),
                    ),
                )
            ),
        )


def test_route_spec_rejects_empty_and_duplicate_targets() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        RouteSpec(match=MessageMatch(intent="update"), targets=())
    with pytest.raises(ValueError, match="duplicate actor ids"):
        RouteSpec(
            match=MessageMatch(intent="update"),
            targets=("frontend", "frontend"),
        )


def test_run_spec_with_actors_requires_transport() -> None:
    with pytest.raises(ValueError, match="requires an explicit transport"):
        RunSpec(actors=(ActorSpec(id="worker"),))


def test_orchestrator_rejects_non_fabric_transport_result() -> None:
    spec = RunSpec(
        actors=(ActorSpec(id="worker"),),
        transport=lambda actors, routing: {},
    )
    with pytest.raises(TypeError, match="must return BusFabric"):
        run_orchestrator(spec)


def test_bus_rejects_routed_message_to_unknown_actor() -> None:
    source = _RecordingChannel()
    bus = Bus(peer_ids=("source",), bus_channels={"source": source})
    inner = command_message(RoutedMessage("missing", command_message(Reset())))
    with pytest.raises(BusRoutingError, match="targets unknown actor"):
        bus._route(inner, "source")


class _ExplodingBus:
    def __init__(self) -> None:
        self.published = []
        self.closed = False

    def step(self) -> int:
        raise BusRoutingError("unrouteable")

    def publish(self, message) -> int:
        self.published.append(message)
        return 1

    def close(self) -> None:
        self.closed = True


def test_bus_thread_stops_runtime_and_surfaces_failure() -> None:
    bus = _ExplodingBus()
    runtime = AppRuntime(app_spec=None)
    bus_thread = BusThread(bus, on_failure=lambda exc: runtime.stop())
    handle = AppHandle(
        runtime=runtime,
        items=[],
        results={},
        bus_thread=bus_thread,
    )
    bus_thread.start()

    deadline = time.monotonic() + 2.0
    while bus_thread.failure is None and time.monotonic() < deadline:
        time.sleep(0.001)

    with pytest.raises(RuntimeError, match="message bus failed") as caught:
        handle.wait()
    assert isinstance(caught.value.__cause__, BusRoutingError)
    assert runtime.is_stopped()
    assert bus.closed
    assert any(isinstance(message.payload, Error) for message in bus.published)


class _BlockingQueueProbe:
    def __init__(self) -> None:
        self.messages = []

    def put(self, message) -> None:
        self.messages.append(message)

    def put_nowait(self, message) -> None:
        raise AssertionError("authoritative field updates must not use lossy put_nowait")


@pytest.mark.parametrize(
    "payload",
    (
        FieldReplace(field_id="field", values=np.asarray([1.0])),
        FieldAppend(
            field_id="field",
            append_dim="time",
            values=np.asarray([2.0]),
            coord_values=np.asarray([1.0]),
        ),
    ),
)
def test_mpqueue_field_updates_use_lossless_backpressure(payload) -> None:
    outbound = _BlockingQueueProbe()
    endpoint = PipeEndpoint(
        inbound=queue.Queue(),
        outbound=outbound,
        mode="mpqueue",
        name="test",
    )
    message = update_message(payload)
    endpoint.send(message)
    assert outbound.messages == [message]


def test_script_worker_surfaces_uncaught_script_error(monkeypatch) -> None:
    channel = _RecordingChannel()

    def fail(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("script failed")

    monkeypatch.setattr("compneurovis.core.runtime.actor_launchers.runpy.run_path", fail)
    _script_actor_worker("broken.py", channel, None, threading.Event())

    assert channel.closed
    assert len(channel.messages) == 1
    assert isinstance(channel.messages[0].payload, Error)
    assert "script failed" in channel.messages[0].payload.message


class _FailingActor(ActorBase):
    def is_active(self) -> bool:
        return True

    def tick(self) -> None:
        raise RuntimeError("actor failed")


def test_actor_runner_emits_error_before_closing_failed_channel() -> None:
    channel = _RecordingChannel()
    with pytest.raises(RuntimeError, match="actor failed"):
        run_actor(_FailingActor, channel)

    assert channel.closed
    assert len(channel.messages) == 1
    assert isinstance(channel.messages[0].payload, Error)
    assert "actor failed" in channel.messages[0].payload.message


def test_thread_actor_failure_stops_runtime_and_emits_error() -> None:
    channel = _RecordingChannel()
    runtime = AppRuntime(app_spec=None)
    launcher = ThreadActorLauncher(_FailingActor, runtime, channel)
    launcher.start()
    launcher.run()

    deadline = time.monotonic() + 2.0
    while not runtime.is_stopped() and time.monotonic() < deadline:
        time.sleep(0.001)
    launcher.stop()

    assert runtime.is_stopped()
    assert any(isinstance(message.payload, Error) for message in channel.messages)


def test_app_handle_stops_bus_before_closing_actor_hosts() -> None:
    events = []

    class _BusThread:
        def stop(self):
            events.append("bus")

    class _Host:
        def stop(self):
            events.append("host")

    handle = AppHandle(
        runtime=AppRuntime(app_spec=None),
        items=[(ActorSpec(id="worker"), _Host())],
        results={},
        bus_thread=_BusThread(),
    )
    handle.stop()

    assert events == ["bus", "host"]
