from __future__ import annotations

import queue
import multiprocessing as mp
import threading
import time

import numpy as np
import pytest

import compneurovis.core.runtime.actor_host as actor_host_module
import compneurovis.inline.backend as inline_backend_module
from compneurovis.core.app_spec import AppSpec
from compneurovis.core.diagnostics import DiagnosticsSpec
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
    _send_error_once,
    _script_actor_worker,
    configure_multiprocessing,
)
from compneurovis.core.runtime.actor import ActorBase
from compneurovis.core.runtime.app import AppRuntime
from compneurovis.core.runtime.app_handle import AppHandle
from compneurovis.core.runtime.actor_host import ActorHost
from compneurovis.core.runtime.bus import Bus, BusFabric, BusRoutingError, BusThread
from compneurovis.core.runtime.performance import (
    acquire_perf_logging_configuration,
    clear_perf_logging_configuration,
    configure_perf_logging,
    perf_logging_enabled,
    release_perf_logging_configuration,
)
from compneurovis.core.runtime.process_context import spawn_context
from compneurovis.core.runtime.run import run_actor, run_orchestrator, start_app
from compneurovis.inline.data_producers import SnapshotProducer
from compneurovis.transports.pipe import PipeEndpoint


class _RecordingChannel:
    def __init__(self) -> None:
        self.messages = []
        self.closed = False
        self.close_calls = 0

    def send(self, message) -> None:
        self.messages.append(message)

    def poll(self):
        return []

    def close(self) -> None:
        self.closed = True
        self.close_calls += 1


def test_runtime_uses_owned_spawn_context_without_replacing_process_default(
    monkeypatch,
) -> None:
    freeze_support_calls = []

    def reject_global_start_method(*args, **kwargs):
        del args, kwargs
        raise AssertionError("must not replace the embedding process's start method")

    monkeypatch.setattr(mp, "set_start_method", reject_global_start_method)
    monkeypatch.setattr(mp, "freeze_support", lambda: freeze_support_calls.append(True))

    configure_multiprocessing()

    assert freeze_support_calls == [True]
    assert spawn_context().get_start_method() == "spawn"


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


def test_perf_logging_leases_restore_prior_configuration_out_of_order() -> None:
    clear_perf_logging_configuration()
    configure_perf_logging(DiagnosticsSpec())
    first = acquire_perf_logging_configuration(
        DiagnosticsSpec(perf_log_enabled=True)
    )
    second = acquire_perf_logging_configuration(DiagnosticsSpec())
    try:
        assert not perf_logging_enabled()
        release_perf_logging_configuration(first)
        assert not perf_logging_enabled()
        release_perf_logging_configuration(second)
        assert not perf_logging_enabled()
        release_perf_logging_configuration(second)
    finally:
        release_perf_logging_configuration(first)
        release_perf_logging_configuration(second)
        clear_perf_logging_configuration()


def test_inline_backend_perf_window_reports_snapshot_rate_and_bytes(
    monkeypatch,
) -> None:
    events = []
    monkeypatch.setattr(inline_backend_module, "perf_logging_enabled", lambda: True)
    monkeypatch.setattr(
        inline_backend_module,
        "perf_log",
        lambda component, event, **fields: events.append(
            (component, event, fields)
        ),
    )
    values = np.ones((2, 3), dtype=np.float32)
    producer = SnapshotProducer(
        field_id="surface",
        dims=("y", "x"),
        coords={
            "y": np.array([0.0, 1.0], dtype=np.float32),
            "x": np.array([0.0, 1.0, 2.0], dtype=np.float32),
        },
        read=lambda: values,
        replace_includes_coords=True,
    )
    backend = inline_backend_module.InlineBackend(
        series=[],
        controls=[],
        actions=[],
        fields=[producer],
        derived_values=[],
        initial_values=[],
        step=None,
    )
    backend._perf_window_started = time.monotonic() - 1.1

    backend.tick()

    snapshot = next(fields for _, event, fields in events if event == "snapshot_field")
    window = next(fields for _, event, fields in events if event == "tick_window")
    assert snapshot["payload_bytes"] == values.nbytes + (2 + 3) * 4
    assert window["snapshot_count"] == 1
    assert window["snapshot_bytes"] == snapshot["payload_bytes"]


def test_actor_host_perf_window_reports_tick_and_flush_phases(monkeypatch) -> None:
    events = []
    monkeypatch.setattr(actor_host_module, "perf_logging_enabled", lambda: True)
    monkeypatch.setattr(
        actor_host_module,
        "perf_log",
        lambda component, event, **fields: events.append(
            (component, event, fields)
        ),
    )

    class _TickActor(ActorBase):
        def is_active(self) -> bool:
            return True

        def tick(self) -> None:
            self.emit_update(Error("sample"))

    channel = _RecordingChannel()
    host = ActorHost(channel)
    host.start(_TickActor, None)
    host._perf_window_started = time.monotonic() - 1.1

    host.step()

    window = next(fields for _, event, fields in events if event == "step_window")
    assert len(channel.messages) == 1
    assert window["step_count"] == 1
    assert window["outbound_count"] == 1
    assert window["tick_ms_total"] >= 0.0
    assert window["flush_ms_total"] >= 0.0


def test_orchestrator_validation_failure_closes_fabric_and_restores_diagnostics() -> None:
    peer = _RecordingChannel()
    bus_side = _RecordingChannel()
    fabric = BusFabric(
        peer_channels={"wrong": peer},
        bus=Bus(peer_ids=("wrong",), bus_channels={"wrong": bus_side}),
    )
    spec = RunSpec(
        actors=(ActorSpec(id="worker"),),
        transport=lambda actors, routing: fabric,
        diagnostics=DiagnosticsSpec(),
    )

    configure_perf_logging(DiagnosticsSpec(perf_log_enabled=True))
    try:
        with pytest.raises(ValueError, match="do not match RunSpec actors"):
            run_orchestrator(spec)

        assert peer.close_calls == 1
        assert bus_side.close_calls == 1
        assert perf_logging_enabled()
    finally:
        clear_perf_logging_configuration()


def test_orchestrator_publish_failure_unwinds_allocated_resources() -> None:
    class _PublishFailureBus(Bus):
        def publish(self, message, *, targets=None):
            del message, targets
            raise RuntimeError("publish failed")

    peer = _RecordingChannel()
    bus_side = _RecordingChannel()
    fabric = BusFabric(
        peer_channels={"worker": peer},
        bus=_PublishFailureBus(
            peer_ids=("worker",),
            bus_channels={"worker": bus_side},
        ),
    )
    spec = RunSpec(
        app_spec=AppSpec(),
        actors=(ActorSpec(id="worker"),),
        transport=lambda actors, routing: fabric,
        diagnostics=DiagnosticsSpec(perf_log_enabled=True),
    )

    configure_perf_logging(DiagnosticsSpec())
    try:
        with pytest.raises(RuntimeError, match="publish failed"):
            run_orchestrator(spec)

        assert peer.close_calls == 1
        assert bus_side.close_calls == 1
        assert not perf_logging_enabled()
    finally:
        clear_perf_logging_configuration()


def test_app_handle_owns_diagnostics_and_transport_until_stop() -> None:
    peer = _RecordingChannel()
    bus_side = _RecordingChannel()
    fabric = BusFabric(
        peer_channels={"worker": peer},
        bus=Bus(peer_ids=("worker",), bus_channels={"worker": bus_side}),
    )
    spec = RunSpec(
        actors=(ActorSpec(id="worker"),),
        transport=lambda actors, routing: fabric,
        diagnostics=DiagnosticsSpec(perf_log_enabled=True),
    )

    configure_perf_logging(DiagnosticsSpec())
    try:
        handle = run_orchestrator(spec)
        assert handle is not None
        assert perf_logging_enabled()

        handle.stop()
        handle.stop()

        assert peer.close_calls == 1
        assert bus_side.close_calls == 1
        assert not perf_logging_enabled()
    finally:
        clear_perf_logging_configuration()


def test_start_app_failure_stops_started_hosts_and_releases_runtime_ownership() -> None:
    events = []

    class _Host:
        def __init__(self, name, *, fail_start=False):
            self.name = name
            self.fail_start = fail_start

        def start(self):
            events.append(f"start:{self.name}")
            if self.fail_start:
                raise RuntimeError("host start failed")

        def stop(self):
            events.append(f"stop:{self.name}")

    peer_channels = {
        "first": _RecordingChannel(),
        "second": _RecordingChannel(),
    }
    bus_channels = {
        "first": _RecordingChannel(),
        "second": _RecordingChannel(),
    }
    fabric = BusFabric(
        peer_channels=peer_channels,
        bus=Bus(peer_ids=("first", "second"), bus_channels=bus_channels),
    )
    spec = RunSpec(
        actors=(
            ActorSpec(id="first", host_source=lambda runtime, channel: _Host("first")),
            ActorSpec(
                id="second",
                host_source=lambda runtime, channel: _Host("second", fail_start=True),
            ),
        ),
        transport=lambda actors, routing: fabric,
        diagnostics=DiagnosticsSpec(perf_log_enabled=True),
    )

    configure_perf_logging(DiagnosticsSpec())
    try:
        with pytest.raises(RuntimeError, match="host start failed"):
            start_app(spec)

        assert events == [
            "start:first",
            "start:second",
            "stop:second",
            "stop:first",
        ]
        assert not perf_logging_enabled()
        assert all(channel.closed for channel in peer_channels.values())
        assert all(channel.closed for channel in bus_channels.values())
    finally:
        clear_perf_logging_configuration()


def test_bus_rejects_routed_message_to_unknown_actor() -> None:
    source = _RecordingChannel()
    bus = Bus(peer_ids=("source",), bus_channels={"source": source})
    inner = command_message(RoutedMessage("missing", command_message(Reset())))
    with pytest.raises(BusRoutingError, match="targets unknown actor"):
        bus._route(inner, "source")


def test_bus_delivers_explicit_route_back_to_source_actor() -> None:
    source = _RecordingChannel()
    routing = RoutingSpec(
        routes=(
            RouteSpec(
                match=MessageMatch(intent="update"),
                targets=("source",),
            ),
        )
    )
    bus = Bus(
        peer_ids=("source",),
        bus_channels={"source": source},
        routing=routing,
    )
    message = update_message(Error("loopback"))

    assert bus._route(message, "source") == (("source", message),)


def test_bus_match_distinguishes_missing_values_from_explicit_none() -> None:
    bus = Bus(peer_ids=(), bus_channels={})
    message = update_message(Error("failure"))

    assert not bus._matches(
        message,
        MessageMatch(tags={"missing": None}),
    )
    assert not bus._matches(
        message,
        MessageMatch(attrs={"missing": None}),
    )
    assert bus._matches(
        update_message(Error("failure"), tags={"present": None}),
        MessageMatch(tags={"present": None}),
    )


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


class _ShutdownBrokenPipeBus:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.closed = False

    def step(self) -> int:
        self.entered.set()
        self.release.wait(timeout=2.0)
        raise BrokenPipeError("closed during shutdown")

    def publish(self, message) -> int:
        raise AssertionError(f"shutdown failure was published: {message}")

    def close(self) -> None:
        self.closed = True


def test_bus_thread_ignores_transport_close_after_shutdown_requested() -> None:
    bus = _ShutdownBrokenPipeBus()
    failures = []
    bus_thread = BusThread(bus, on_failure=failures.append)
    bus_thread.start()
    assert bus.entered.wait(timeout=2.0)

    release = threading.Timer(0.01, bus.release.set)
    release.start()
    bus_thread.stop()
    release.join()

    assert bus_thread.failure is None
    assert failures == []
    assert bus.closed
    assert bus_thread._thread is not None
    assert not bus_thread._thread.is_alive()


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
    with pytest.raises(RuntimeError, match="script failed"):
        _script_actor_worker("broken.py", channel, None, threading.Event())

    assert channel.closed
    assert len(channel.messages) == 1
    assert isinstance(channel.messages[0].payload, Error)
    assert "script failed" in channel.messages[0].payload.message


def test_script_worker_reuses_source_staged_during_spawn_bootstrap(monkeypatch) -> None:
    from compneurovis.core.runtime import actor_launchers
    from compneurovis import _source_runtime

    channel = _RecordingChannel()
    source = object()
    calls = []
    actor_launchers.stage_bootstrap_script_payload("source", source)
    monkeypatch.setattr(
        actor_launchers.runpy,
        "run_path",
        lambda *_args, **_kwargs: pytest.fail("staged source must prevent rerun"),
    )
    monkeypatch.setattr(
        _source_runtime,
        "run_source_actor",
        lambda actual, actual_channel: calls.append((actual, actual_channel)),
    )

    _script_actor_worker("already-imported.py", channel, None, threading.Event())

    assert calls == [(source, channel)]
    assert channel.closed


def test_nested_actor_failure_is_reported_only_once() -> None:
    channel = _RecordingChannel()
    failure = RuntimeError("one failure")

    _send_error_once(channel, failure)
    _send_error_once(channel, failure)

    assert len(channel.messages) == 1
    assert isinstance(channel.messages[0].payload, Error)


class _FailingActor(ActorBase):
    def is_active(self) -> bool:
        return True

    def tick(self) -> None:
        raise RuntimeError("actor failed")


class _LifecycleActor(ActorBase):
    def __init__(self) -> None:
        super().__init__()
        self.shutdown_calls = 0

    def shutdown(self) -> None:
        self.shutdown_calls += 1


def test_actor_host_shutdown_and_channel_close_are_idempotent() -> None:
    channel = _RecordingChannel()
    actor = _LifecycleActor()
    host = ActorHost(channel=channel)
    host.start(lambda: actor, None)

    host.stop()
    host.stop()

    assert actor.shutdown_calls == 1
    assert channel.close_calls == 1


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


def test_app_handle_stop_is_best_effort_and_idempotent() -> None:
    events = []

    class _Host:
        def __init__(self, name, *, fails=False):
            self.name = name
            self.fails = fails

        def stop(self):
            events.append(self.name)
            if self.fails:
                raise RuntimeError(f"{self.name} failed")

    handle = AppHandle(
        runtime=AppRuntime(app_spec=None),
        items=[
            (ActorSpec(id="first"), _Host("first")),
            (ActorSpec(id="failing"), _Host("failing", fails=True)),
            (ActorSpec(id="last"), _Host("last")),
        ],
        results={},
    )

    with pytest.raises(RuntimeError, match="failing failed"):
        handle.stop()
    handle.stop()

    assert events == ["last", "failing", "first"]


def test_app_handle_surfaces_nonzero_actor_process_exit() -> None:
    class _FailedProcess:
        exitcode = 7

        @staticmethod
        def is_alive():
            return False

    class _ProcessHost:
        _process = _FailedProcess()

        @staticmethod
        def stop():
            return None

    handle = AppHandle(
        runtime=AppRuntime(app_spec=None),
        items=[(ActorSpec(id="worker"), _ProcessHost())],
        results={},
    )

    with pytest.raises(RuntimeError, match="'worker' \\(exit code 7\\)"):
        handle.wait()


def test_vispy_host_restores_owned_signal_and_surface_format() -> None:
    import signal

    from PyQt6 import QtGui

    from compneurovis.frontends.vispy.host import (
        VispyActorHost,
        _configure_qt_surface_format,
    )

    class _QApp:
        quit_calls = 0

        def quit(self):
            self.quit_calls += 1

    host = VispyActorHost(_LifecycleActor, AppRuntime(app_spec=None))
    host._qapp = _QApp()
    previous_signal = signal.getsignal(signal.SIGINT)
    previous_surface = QtGui.QSurfaceFormat(QtGui.QSurfaceFormat.defaultFormat())
    try:
        host._install_sigint_handler()
        owned_signal = signal.getsignal(signal.SIGINT)
        assert owned_signal is host._sigint_handler
        owned_signal(signal.SIGINT, None)
        assert host._qapp.quit_calls == 1

        before, owned = _configure_qt_surface_format()
        host._previous_qt_surface_format = before
        host._owned_qt_surface_format = owned

        host._restore_sigint_handler()
        host._restore_qt_surface_format()

        assert signal.getsignal(signal.SIGINT) is previous_signal
        assert QtGui.QSurfaceFormat.defaultFormat() == before
    finally:
        signal.signal(signal.SIGINT, previous_signal)
        QtGui.QSurfaceFormat.setDefaultFormat(previous_surface)


def test_vispy_host_stops_actor_when_timer_cleanup_fails() -> None:
    from compneurovis.frontends.vispy.host import VispyActorHost

    class _FailingTimer:
        @staticmethod
        def stop():
            raise RuntimeError("timer failed")

    channel = _RecordingChannel()
    actor = _LifecycleActor()
    host = VispyActorHost(lambda: actor, AppRuntime(app_spec=None), channel)
    host.actor = actor
    host.timer = _FailingTimer()

    with pytest.raises(RuntimeError, match="timer failed"):
        host.stop()
    host.stop()

    assert actor.shutdown_calls == 1
    assert channel.close_calls == 1
