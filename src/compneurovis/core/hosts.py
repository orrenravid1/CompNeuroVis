from __future__ import annotations

import multiprocessing as mp
import runpy
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, TypeAlias

from compneurovis.core._perf import clear_perf_logging_configuration, configure_perf_logging, perf_log
from compneurovis.core.actor import ActorBase, ActorSource
from compneurovis.core.app import AppSpec, DiagnosticsSpec
from compneurovis.core.channel import Channel
from compneurovis.core.messages import Error, StopActor, update_message


class Startable(Protocol):
    """Uniform lifecycle interface for in-process hosts and subprocess actors."""
    def start(self) -> None: ...
    def run(self) -> None: ...
    def stop(self) -> None: ...


# Callable[[AppRuntime, Channel | None], Startable]
ActorHostSource: TypeAlias = Callable[..., Startable]
# Callable[[list[ActorSpec], RoutingSpec | None], dict[str, Channel] | BusFabric]
TransportFactory: TypeAlias = Callable[..., Any]


def configure_multiprocessing() -> None:
    mp.freeze_support()
    mp.set_start_method("spawn", force=True)


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
    """Holds a channel open for a remotely-connected actor.

    Used by run_orchestrator for actors with host_source=None. Does not spawn
    or own any process — the remote actor connects independently.
    """

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


class ThreadActorHost(ActorHost):
    """ActorHost whose step loop runs in a daemon thread."""

    def __init__(
        self,
        actor_source: ActorSource,
        runtime: "AppRuntime",
        channel: Channel,
    ) -> None:
        super().__init__(channel=channel)
        self._actor_source = actor_source
        self._runtime = runtime
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        super().start(self._actor_source, self._runtime.app_spec)

    def run(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        try:
            while not self.should_stop():
                started = time.monotonic()
                self.step()
                remaining = self.idle_sleep() - (time.monotonic() - started)
                if remaining > 0:
                    time.sleep(remaining)
        except (BrokenPipeError, OSError):
            pass
        finally:
            self.stop()


def _actor_process_worker(
    actor_source: ActorSource,
    app_spec: AppSpec | None,
    channel: Channel,
    host_class: type[ActorHost],
    diagnostics: DiagnosticsSpec | None,
    stop_event,
) -> None:
    host = host_class(channel=channel)
    try:
        configure_diagnostics(diagnostics)
        host.start(actor_source, app_spec)
        perf_log("actor_process", "initialize", host_type=host_class.__name__)
        while not stop_event.is_set() and not host.should_stop():
            started = time.monotonic()
            host.step()
            delay = host.idle_sleep()
            if delay > 0:
                remaining = delay - (time.monotonic() - started)
                if remaining > 0:
                    time.sleep(remaining)
    except Exception as exc:  # pragma: no cover - worker safety net
        detail = "".join(traceback.format_exception(exc))
        perf_log("actor_process", "error", error_type=type(exc).__name__, message=str(exc))
        channel.send(update_message(Error(detail)))
    finally:
        host.stop()


@dataclass(slots=True)
class ActorProcess:
    actor_source: ActorSource
    app_spec: AppSpec | None
    channel: Channel
    host_class: type[ActorHost] = field(default=ActorHost)
    diagnostics: DiagnosticsSpec | None = None
    _stop_event: Any = field(init=False)
    _process: mp.Process | None = field(init=False, default=None)

    def __post_init__(self) -> None:
        self._stop_event = mp.Event()

    def start(self) -> None:
        process = mp.Process(
            target=_actor_process_worker,
            args=(self.actor_source, self.app_spec, self.channel, self.host_class, self.diagnostics, self._stop_event),
        )
        process.start()
        self._process = process
        self.channel.close()

    def run(self) -> None:
        pass

    def stop(self) -> None:
        self._stop_event.set()
        if self._process is not None:
            self._process.join(timeout=1)
            if self._process.is_alive():
                self._process.terminate()
                self._process.join()


# --------------------------------------------------------------------------- #
# Script actor — subprocess launched by re-running the user's script          #
# --------------------------------------------------------------------------- #

_g_script_actor_channel: Channel | None = None


def get_script_actor_channel() -> Channel | None:
    """Return the channel if this process was spawned as a script actor."""
    return _g_script_actor_channel


def _set_script_actor_channel(channel: Channel) -> None:
    global _g_script_actor_channel
    _g_script_actor_channel = channel


def _script_actor_worker(script_path: str, channel: Channel) -> None:
    """Subprocess entry point for script-defined actors.

    Sets the process-level channel flag then re-runs the user's script as
    __main__. The script detects get_script_actor_channel() is set and runs as
    an actor.

    Must be top-level in this module so multiprocessing can resolve it by
    qualified name. Do not move or rename.
    """
    _set_script_actor_channel(channel)
    inline_module = sys.modules.get("compneurovis.inline")
    reset_inline = getattr(inline_module, "_reset_inline_session", None)
    if callable(reset_inline):
        reset_inline()
    runpy.run_path(script_path, run_name="__main__")


class ScriptActorProcess:
    """Startable that spawns an actor subprocess by re-running a script.

    The script is the actor source. Pickling actor state is not required: it is
    reconstructed fresh when the script re-runs. This is the right strategy for
    NEURON, JAX, and any model that builds non-picklable state.
    """

    def __init__(self, script_path: str, channel: Channel) -> None:
        self._script_path = script_path
        self._channel = channel
        self._process: mp.Process | None = None

    def start(self) -> None:
        self._process = mp.Process(
            target=_script_actor_worker,
            args=(self._script_path, self._channel),
        )
        self._process.start()
        self._channel.close()

    def run(self) -> None:
        pass

    def stop(self) -> None:
        if self._process is None:
            return
        self._process.join(timeout=2)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join()


# --------------------------------------------------------------------------- #
# AppHandle — returned by start_app() for non-blocking runs                   #
# --------------------------------------------------------------------------- #

class AppHandle:
    """Handle for an orchestrated app run.

    Returned by run_orchestrator() (empty items — open slots only) and by
    start_app() (which composes run_orchestrator + per-actor spawn). Carries:

    - runtime:   the AppRuntime (stop signal, optional startup AppSpec)
    - channels:  per-actor channels, keyed by actor id
    - actors:    declarative ActorSpec list (topology)
    - items:     (spec, host) pairs for locally-spawned actors (empty for a
                 pure orchestrator where every client dials in remotely)
    - results:   actor_id → host.run() return value (e.g. notebook widget)
    """

    def __init__(
        self,
        *,
        runtime: "AppRuntime",  # type: ignore[name-defined]
        items: list,
        results: dict,
        channels: dict | None = None,
        actors: list | None = None,
        bus_thread: "Any | None" = None,
    ) -> None:
        self._runtime = runtime
        self.items = items
        self.results = results
        self.channels: dict = channels or {}
        self.actors: list = actors or []
        self._bus_thread = bus_thread

    @property
    def runtime(self) -> "AppRuntime":  # type: ignore[name-defined]
        return self._runtime

    def widget(self, actor_id: str = "frontend") -> Any:
        """Return the widget produced by the named actor's run()."""
        return self.results.get(actor_id)

    def wait(self) -> None:
        """Block until the run finishes, then stop all actors.

        Single orchestration lifecycle for every bundled launch — desktop,
        headless, and pure orchestrator all go through here:

        - Foreground actor present (e.g. Qt): run its event loop on the
          calling (main) thread; stop everything when it exits.
        - No foreground actor (headless / all-remote orchestrator): block
          until stop() is signalled or every hosted subprocess has exited.

        The notebook path never calls wait(): start_app() returns the widget
        and an asyncio task drives the run inside the kernel.
        """
        fg = [(spec, host) for spec, host in self.items if spec.runs_in_foreground]
        if fg:
            _, fg_host = fg[0]
            try:
                fg_host.run()
            finally:
                self.stop()
            return

        processes = [
            p
            for p in (getattr(host, "_process", None) for _, host in self.items)
            if p is not None
        ]
        try:
            while not self._runtime.is_stopped():
                if processes and not any(p.is_alive() for p in processes):
                    break
                time.sleep(0.05)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        self._runtime.stop()
        for _, host in reversed(self.items):
            host.stop()
        if self._bus_thread is not None:
            self._bus_thread.stop()


__all__ = [
    "ActorHost",
    "ActorHostSource",
    "ActorProcess",
    "AppHandle",
    "ConnectionSlotHost",
    "ScriptActorProcess",
    "Startable",
    "ThreadActorHost",
    "TransportFactory",
    "configure_diagnostics",
    "configure_multiprocessing",
    "get_script_actor_channel",
    "resolve_actor_source",
    "resolve_interaction_target_source",
]
