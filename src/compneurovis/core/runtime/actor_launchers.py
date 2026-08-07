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
from compneurovis.core.runtime.process_context import prepare_multiprocessing, spawn_context
from compneurovis.core.app_spec import AppSpec
from compneurovis.core.diagnostics import DiagnosticsSpec, configure_diagnostics
from compneurovis.core.messages import Error, update_message

if TYPE_CHECKING:
    from compneurovis.core.runtime.app import AppRuntime


def configure_multiprocessing() -> None:
    """Prepare multiprocessing without changing the application's default context."""

    prepare_multiprocessing()


_ERROR_REPORTED_ATTR = "_compneurovis_error_reported"


def _send_error_once(channel: Channel, exc: BaseException) -> None:
    """Report one failure as it propagates through nested actor runners."""

    if getattr(exc, _ERROR_REPORTED_ATTR, False):
        return
    try:
        setattr(exc, _ERROR_REPORTED_ATTR, True)
    except (AttributeError, TypeError):
        # Ordinary exceptions accept attributes. If an exotic exception does
        # not, still prefer reporting it over hiding the failure.
        pass
    detail = "".join(traceback.format_exception(exc))
    try:
        channel.send(update_message(Error(detail)))
    except (BrokenPipeError, OSError):
        pass


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
        self._channel = channel
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
        except Exception as exc:
            perf_log(
                "thread_actor",
                "error",
                error_type=type(exc).__name__,
                message=str(exc),
            )
            _send_error_once(self._channel, exc)
            self._runtime.stop()
        finally:
            self.stop()

    def stop(self) -> None:
        failure = None
        try:
            self._host.stop()
        except Exception as exc:
            failure = exc
        finally:
            if (
                self._thread is not None
                and self._thread.is_alive()
                and threading.current_thread() is not self._thread
            ):
                self._thread.join(timeout=1)
        if failure is not None:
            raise failure


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
    except KeyboardInterrupt:
        # Console Ctrl+C is delivered to child processes too; it is a normal stop.
        pass
    except Exception as exc:  # pragma: no cover - worker safety net
        perf_log("actor_process", "error", error_type=type(exc).__name__, message=str(exc))
        _send_error_once(channel, exc)
        raise
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
        self._stop_event = spawn_context().Event()

    def start(self) -> None:
        process = spawn_context().Process(
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
_g_script_actor_stop_event: Any | None = None
_g_bootstrap_script_payload: tuple[str, Any] | None = None


def get_script_actor_channel() -> Channel | None:
    """Return the channel if this process was spawned as a script actor."""
    return _g_script_actor_channel


def get_script_actor_stop_event() -> Any | None:
    """Return the cooperative stop event for a spawned script actor."""
    return _g_script_actor_stop_event


def _set_script_actor_runtime(channel: Channel, stop_event: Any) -> None:
    global _g_script_actor_channel, _g_script_actor_stop_event
    _g_script_actor_channel = channel
    _g_script_actor_stop_event = stop_event


def stage_bootstrap_script_payload(kind: str, payload: Any) -> None:
    """Retain authoring completed while multiprocessing imports __mp_main__."""
    global _g_bootstrap_script_payload
    _g_bootstrap_script_payload = (kind, payload)


def _consume_bootstrap_script_payload() -> tuple[str, Any] | None:
    global _g_bootstrap_script_payload
    payload = _g_bootstrap_script_payload
    _g_bootstrap_script_payload = None
    return payload


ScriptBeforeRun = Callable[[], None]


def _script_actor_worker(
    script_path: str,
    channel: Channel,
    before_run: ScriptBeforeRun | None,
    stop_event,
) -> None:
    _set_script_actor_runtime(channel, stop_event)
    try:
        staged = _consume_bootstrap_script_payload()
        if before_run is not None:
            before_run()
        if staged is None:
            runpy.run_path(script_path, run_name="__main__")
        else:
            kind, payload = staged
            from compneurovis._source_runtime import (
                run_source_actor,
                run_sources_actor,
            )

            if kind == "source":
                run_source_actor(payload, channel)
            elif kind == "sources":
                run_sources_actor(payload, channel)
            else:
                raise RuntimeError(f"Unknown staged script payload kind {kind!r}")
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # pragma: no cover - worker safety net
        perf_log("script_actor", "error", error_type=type(exc).__name__, message=str(exc))
        _send_error_once(channel, exc)
        raise
    finally:
        channel.close()


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
        self._stop_event = spawn_context().Event()
        self._process: mp.Process | None = None

    def start(self) -> None:
        self._process = spawn_context().Process(
            target=_script_actor_worker,
            args=(
                self._script_path,
                self._channel,
                self._before_run,
                self._stop_event,
            ),
        )
        self._process.start()
        self._channel.close()

    def run(self) -> None:
        pass

    def stop(self) -> None:
        if self._process is None:
            return
        self._stop_event.set()
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

    _set_script_actor_runtime(channel, None)
    try:
        if before_run is not None:
            before_run()
        source = cloudpickle.loads(builder_blob)()
        run_source_actor(source, channel)
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # pragma: no cover - worker safety net
        # The builder runs here, in the child. Without this, a build failure
        # (e.g. a bad source spec) just kills the process silently and the
        # kernel keeps an empty app shell. Mirror _actor_process_worker and
        # surface the traceback over the channel as an Error update.
        perf_log("builder_actor", "error", error_type=type(exc).__name__, message=str(exc))
        _send_error_once(channel, exc)
        raise
    finally:
        channel.close()


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
        self._process = spawn_context().Process(
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
    "get_script_actor_stop_event",
]
