from __future__ import annotations

import multiprocessing as mp
import time
from typing import TYPE_CHECKING, Any

from compneurovis.core.app_spec import AppSpec
from compneurovis.core.runtime.channel import Channel
from compneurovis.core.runtime.actor_host import ConnectionSlotHost
from compneurovis.core.runtime.actor_launchers import (
    _send_error_once,
    configure_multiprocessing,
)
from compneurovis.core.runtime.app_handle import AppHandle
from compneurovis.core.diagnostics import acquire_diagnostics, release_diagnostics
from compneurovis.core.runtime import AppRuntime
from compneurovis.core.runtime.bus import BusFabric, BusThread
from compneurovis.core.run_spec import RunSpec

if TYPE_CHECKING:
    from compneurovis.core.runtime.actor import ActorSource


# --------------------------------------------------------------------------- #
# Orchestrator — the central primitive                                        #
# --------------------------------------------------------------------------- #


def run_orchestrator(run_spec: RunSpec) -> AppHandle | None:
    """Open the transport fabric and create AppRuntime — spawn NO actors.

    Foundation primitive. Returns an AppHandle exposing per-actor channels
    (``handle.channels[actor_id]``), the runtime, and the declared actor
    actor wiring. Does not start any host. ``items`` is empty.

    Composed with:
    - ``start_app(spec)`` — bundled sugar: run_orchestrator + spawn each actor
      via its ``ActorSpec.host_source`` lambda (the local launcher policy).
    - ``run_actor(source, channel)`` — client runner called either by
      ``start_app``-style local launchers or by remote worker processes that
      dial into the orchestrator's channels.

    A run is then literally ``run_orchestrator(spec) + (spawn each actor) +
    handle.wait()``. ``start_app`` is the bundled composition; a distributed
    setup composes the same primitives with remote spawns.
    """
    if mp.current_process().name != "MainProcess":
        return None  # subprocess re-entry guard

    configure_multiprocessing()

    actors = list(run_spec.actors)
    fg_actors = [s for s in actors if s.runs_in_foreground]
    if len(fg_actors) > 1:
        raise ValueError(
            f"At most one foreground actor allowed; got {[s.id for s in fg_actors]}."
        )

    runtime = AppRuntime(app_spec=run_spec.app_spec, diagnostics=run_spec.diagnostics)
    diagnostics_token = acquire_diagnostics(runtime.diagnostics)
    transport_fabric: BusFabric | None = None
    handle: AppHandle | None = None
    try:
        if run_spec.transport is None:
            channels = {}
            bus_thread = None
        else:
            transport_result = run_spec.transport(actors, run_spec.routing)
            if not isinstance(transport_result, BusFabric):
                raise TypeError(
                    "RunSpec transport factories must return BusFabric; "
                    f"got {type(transport_result).__name__}"
                )
            transport_fabric = transport_result
            channels = transport_result.peer_channels
            expected_ids = {actor.id for actor in actors}
            actual_ids = set(channels)
            if actual_ids != expected_ids:
                missing = sorted(expected_ids - actual_ids)
                extra = sorted(actual_ids - expected_ids)
                raise ValueError(
                    "Transport peer channels do not match RunSpec actors "
                    f"(missing={missing}, extra={extra})"
                )
            if runtime.app_spec is not None:
                from compneurovis.core.messages import AppSpecDeclared, update_message

                transport_result.bus.publish(
                    update_message(AppSpecDeclared(runtime.app_spec))
                )
            bus_thread = BusThread(
                transport_result.bus,
                on_failure=lambda exc: runtime.stop(),
            )

        handle = AppHandle(
            runtime=runtime,
            items=[],
            results={},
            channels=channels,
            actors=actors,
            bus_thread=bus_thread,
            transport_fabric=transport_fabric,
            diagnostics_token=diagnostics_token,
        )
        if bus_thread is not None:
            bus_thread.start()
        return handle
    except BaseException as startup_error:
        cleanup_errors: list[BaseException] = []
        if handle is not None:
            try:
                handle.stop()
            except BaseException as exc:
                cleanup_errors.append(exc)
        else:
            if transport_fabric is not None:
                try:
                    transport_fabric.close()
                except BaseException as exc:
                    cleanup_errors.append(exc)
            try:
                release_diagnostics(diagnostics_token)
            except BaseException as exc:
                cleanup_errors.append(exc)
        if cleanup_errors:
            raise BaseExceptionGroup(
                "CompNeuroVis startup and cleanup failed",
                [startup_error, *cleanup_errors],
            ) from None
        raise


# --------------------------------------------------------------------------- #
# Bundled launch — orchestrator + per-actor spawn                             #
# --------------------------------------------------------------------------- #


def start_app(run_spec: RunSpec) -> AppHandle | None:
    """Bundled launch = ``run_orchestrator(spec)`` + spawn each actor via its
    ``ActorSpec.host_source`` (the local launcher).

    Literally the composition. Returns the AppHandle that run_orchestrator
    created, with ``items`` populated by the local launchers. Non-foreground
    actors have ``host.run()`` invoked immediately (subprocess spawn no-op,
    asyncio task scheduled, etc.); the foreground actor (if any) is deferred
    to ``AppHandle.wait()``.

    Actors with ``host_source=None`` get a ``ConnectionSlotHost`` — their
    channel is held open for a remote client to dial in (mirroring the pure
    orchestrator path on a per-actor basis).
    """
    handle = run_orchestrator(run_spec)
    if handle is None:
        return None

    try:
        for spec in run_spec.actors:
            channel = handle.channels[spec.id]
            if spec.host_source is None:
                host: Any = ConnectionSlotHost(channel)
            else:
                host = spec.host_source(handle.runtime, channel)
            handle.items.append((spec, host))

        for _, host in handle.items:
            bind_app_handle = getattr(host, "bind_app_handle", None)
            if callable(bind_app_handle):
                bind_app_handle(handle)

        for _, host in handle.items:
            host.start()

        for spec, host in handle.items:
            if not spec.runs_in_foreground:
                result = host.run()
                if result is not None:
                    handle.results[spec.id] = result
    except BaseException as startup_error:
        try:
            handle.stop()
        except BaseException as cleanup_error:
            raise BaseExceptionGroup(
                "CompNeuroVis actor startup and cleanup failed",
                [startup_error, cleanup_error],
            ) from None
        raise

    return handle


def run_app(run_spec: RunSpec) -> None:
    """Bundled launch + block until the run finishes.

    Strictly ``start_app(spec).wait()`` plus a subprocess re-entry guard.
    Blocks until the foreground actor (e.g. Qt event loop) exits, or until
    stop is signalled and all hosted subprocesses exit (headless).
    """
    if mp.current_process().name != "MainProcess":
        return
    handle = start_app(run_spec)
    if handle is not None:
        handle.wait()


# --------------------------------------------------------------------------- #
# Actor client runner — connect one actor to one orchestrator channel         #
# --------------------------------------------------------------------------- #


def run_actor(
    actor_source: "ActorSource",
    channel: Channel,
    *,
    app_spec: AppSpec | None = None,
    runtime: AppRuntime | None = None,
    stop_event: Any | None = None,
) -> None:
    """Run an actor client connected to an orchestrator channel until stop.

    Local: pass a channel from ``run_orchestrator(spec).channels[actor_id]``.
    Distributed: pass a channel obtained from a transport dial-in (e.g.
    a future WebSocket client).

    ``app_spec`` is passed only as this actor's initialization seed. Startup
    AppSpec declaration is handled by runtime/source infrastructure, not by
    actor role code.

    The bundled desktop path's script actor subprocess ends up here, and a
    remote worker invokes this directly. Same code path, different launch.
    """
    from compneurovis.core.runtime.actor_host import ActorHost

    host = ActorHost(channel=channel)
    host.start(actor_source, app_spec)
    try:
        while (
            not host.should_stop()
            and (runtime is None or not runtime.is_stopped())
            and (stop_event is None or not stop_event.is_set())
        ):
            t0 = time.monotonic()
            host.step()
            remaining = host.idle_sleep() - (time.monotonic() - t0)
            if remaining > 0:
                time.sleep(remaining)
    except (BrokenPipeError, OSError):
        pass
    except KeyboardInterrupt:
        # Ctrl+C is delivered to every process in the console group, so an actor
        # subprocess sees it too. That is a normal stop, not a crash.
        pass
    except Exception as exc:
        _send_error_once(channel, exc)
        raise
    finally:
        host.stop()


__all__ = [
    "run_app",
    "run_orchestrator",
    "run_actor",
    "start_app",
]
