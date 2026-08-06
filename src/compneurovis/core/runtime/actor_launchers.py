from __future__ import annotations

import multiprocessing as mp
import pickle
import runpy
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

from compneurovis.core.runtime.performance import perf_log
from compneurovis.core.runtime.actor import ActorSource
from compneurovis.core.runtime.actor_host import ActorHost
from compneurovis.core.runtime.channel import Channel
from compneurovis.core.app_spec import AppSpec
from compneurovis.core.diagnostics import DiagnosticsSpec, configure_diagnostics
from compneurovis.core.messages import Error, update_message

if TYPE_CHECKING:
    from compneurovis.core.runtime.app import AppRuntime


def configure_multiprocessing() -> None:
    mp.freeze_support()
    mp.set_start_method("spawn", force=True)


def assert_spawn_picklable(value: Any, *, label: str) -> None:
    try:
        pickle.dumps(value)
    except Exception as exc:
        raise RuntimeError(
            f"{label} cannot be launched in a subprocess because it is not pickleable. "
            "Use an importable top-level factory/source or keep the actor in-process."
        ) from exc


class ThreadActorLauncher:
    """Startable that runs one ActorHost loop in a daemon thread."""

    def __init__(
        self,
        actor_source: ActorSource,
        runtime: "AppRuntime",
        channel: Channel,
    ) -> None:
        self._host = ActorHost(channel=channel)
        self._actor_source = actor_source
        self._runtime = runtime
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._host.start(self._actor_source, self._runtime.app_spec)

    def run(self) -> None:
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        try:
            while not self._host.should_stop():
                started = time.monotonic()
                self._host.step()
                remaining = self._host.idle_sleep() - (time.monotonic() - started)
                if remaining > 0:
                    time.sleep(remaining)
        except (BrokenPipeError, OSError):
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        self._host.stop()
        if (
            self._thread is not None
            and self._thread.is_alive()
            and threading.current_thread() is not self._thread
        ):
            self._thread.join(timeout=1)


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


_g_script_actor_channel: Channel | None = None


def get_script_actor_channel() -> Channel | None:
    """Return the channel if this process was spawned as a script actor."""
    return _g_script_actor_channel


def _set_script_actor_channel(channel: Channel) -> None:
    global _g_script_actor_channel
    _g_script_actor_channel = channel


ScriptBeforeRun = Callable[[], None]


def _script_actor_worker(
    script_path: str,
    channel: Channel,
    before_run: ScriptBeforeRun | None,
) -> None:
    _set_script_actor_channel(channel)
    if before_run is not None:
        before_run()
    runpy.run_path(script_path, run_name="__main__")


class ScriptActorProcess:
    """Startable that spawns an actor subprocess by re-running a script."""

    def __init__(
        self,
        script_path: str,
        channel: Channel,
        *,
        before_run: ScriptBeforeRun | None = None,
    ) -> None:
        self._script_path = script_path
        self._channel = channel
        self._before_run = before_run
        self._process: mp.Process | None = None

    def start(self) -> None:
        self._process = mp.Process(
            target=_script_actor_worker,
            args=(self._script_path, self._channel, self._before_run),
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


def _builder_actor_worker(builder_blob: bytes, channel: Channel, before_run: "ScriptBeforeRun | None") -> None:
    """Child entry: rebuild the source from the cloudpickled builder, then run
    its backend actor. NEURON/Jaxley objects are constructed *here*, in the
    child's own interpreter — only the builder *function* crossed the spawn
    boundary, never live model objects."""
    import cloudpickle

    from compneurovis._source_runtime import run_source_actor

    _set_script_actor_channel(channel)
    try:
        if before_run is not None:
            before_run()
        source = cloudpickle.loads(builder_blob)()
        run_source_actor(source, channel)
    except Exception as exc:  # pragma: no cover - worker safety net
        # The builder runs here, in the child. Without this, a build failure
        # (e.g. a bad source spec) just kills the process silently and the
        # kernel keeps an empty app shell. Mirror _actor_process_worker and
        # surface the traceback over the channel as an Error update.
        detail = "".join(traceback.format_exception(exc))
        perf_log("builder_actor", "error", error_type=type(exc).__name__, message=str(exc))
        try:
            channel.send(update_message(Error(detail)))
        except (BrokenPipeError, OSError):
            pass


class BuilderActorProcess:
    """Startable that builds the source in a child process from a cloudpickled
    builder callable, then runs its backend actor.

    The notebook's answer to ``ScriptActorProcess``: a notebook cell has no
    script file to re-run, so the construction recipe is shipped as a function.
    The builder must construct from scratch and capture no live model objects
    (same discipline as a desktop launch script).
    """

    def __init__(self, builder: Callable[[], Any], channel: Channel, *, before_run: "ScriptBeforeRun | None" = None) -> None:
        import cloudpickle

        self._builder_blob = cloudpickle.dumps(builder)
        self._channel = channel
        self._before_run = before_run
        self._process: mp.Process | None = None

    def start(self) -> None:
        self._process = mp.Process(
            target=_builder_actor_worker,
            args=(self._builder_blob, self._channel, self._before_run),
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


__all__ = [
    "ActorProcess",
    "BuilderActorProcess",
    "ScriptActorProcess",
    "ThreadActorLauncher",
    "assert_spawn_picklable",
    "configure_multiprocessing",
    "get_script_actor_channel",
]
