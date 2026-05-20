from __future__ import annotations

import multiprocessing as mp
import time
from typing import TYPE_CHECKING, Any

from compneurovis.core.app import AppSpec, RunSpec
from compneurovis.core.hosts import AppHandle, ConnectionSlotHost, configure_diagnostics, configure_multiprocessing
from compneurovis.core.runtime import AppRuntime
from compneurovis.transports import TransportEndpoint

if TYPE_CHECKING:
    from compneurovis.core.actor import ActorSource


# --------------------------------------------------------------------------- #
# Orchestrator — the central primitive                                        #
# --------------------------------------------------------------------------- #


def run_orchestrator(run_spec: RunSpec) -> AppHandle | None:
    """Open the transport fabric and create AppRuntime — spawn NO actors.

    Foundation primitive. Returns an AppHandle exposing per-actor endpoints
    (``handle.endpoints[actor_id]``), the runtime, and the declared actor
    topology. Does not start any host. ``items`` is empty.

    Composed with:
    - ``start_app(spec)`` — bundled sugar: run_orchestrator + spawn each actor
      via its ``ActorSpec.host_source`` lambda (the local launcher policy).
    - ``run_as_backend(source, endpoint)`` / ``run_as_frontend(...)`` — client
      runners called either by ``start_app``-style local launchers or by
      remote worker processes that dial into the orchestrator's endpoints.

    A run is then literally ``run_orchestrator(spec) + (spawn each actor) +
    handle.wait()``. ``start_app`` is the bundled composition; a distributed
    setup composes the same primitives with remote spawns.
    """
    if mp.current_process().name != "MainProcess":
        return None  # subprocess re-entry guard

    configure_multiprocessing()

    fg_actors = [s for s in run_spec.actors if s.runs_in_foreground]
    if len(fg_actors) > 1:
        raise ValueError(
            f"At most one foreground actor allowed; got {[s.id for s in fg_actors]}."
        )

    runtime = AppRuntime(app_spec=run_spec.app_spec, diagnostics=run_spec.diagnostics)
    configure_diagnostics(runtime.diagnostics)

    endpoints = run_spec.transport(run_spec.actors) if run_spec.transport is not None else {}

    return AppHandle(
        runtime=runtime,
        items=[],
        results={},
        endpoints=endpoints,
        actors=list(run_spec.actors),
    )


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
    endpoint is held open for a remote client to dial in (mirroring the pure
    orchestrator path on a per-actor basis).
    """
    handle = run_orchestrator(run_spec)
    if handle is None:
        return None

    for spec in run_spec.actors:
        endpoint = handle.endpoints.get(spec.id)
        if spec.host_source is None:
            host: Any = ConnectionSlotHost(endpoint)
        else:
            host = spec.host_source(handle.runtime, endpoint)
        handle.items.append((spec, host))

    for _, host in handle.items:
        host.start()

    for spec, host in handle.items:
        if not spec.runs_in_foreground:
            result = host.run()
            if result is not None:
                handle.results[spec.id] = result

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
# Client runners — connect to an orchestrator endpoint as a role              #
# --------------------------------------------------------------------------- #


def run_as_backend(
    actor_source: "ActorSource",
    endpoint: TransportEndpoint,
    *,
    app_spec: AppSpec | None = None,
) -> None:
    """Run a backend client connected to an orchestrator endpoint until stop.

    Local: pass an endpoint from ``run_orchestrator(spec).endpoints[actor_id]``.
    Distributed: pass an endpoint obtained from a transport dial-in (e.g.
    a future WebSocket client).

    If ``app_spec`` is provided, the backend host announces it via
    AppSpecSnapshot (backend-authoritative path used by the desktop source
    flow). If ``None``, the backend joins a session whose authoritative spec
    is announced elsewhere.

    Symmetry: the bundled desktop path's ``ScriptBackendProcess`` subprocess
    ends up here (via ``run_source_backend``), and a remote backend worker
    invokes this directly. Same code path, different launch.
    """
    from compneurovis.backends.host import BackendHost

    host = BackendHost(endpoint=endpoint)
    host.start(actor_source, app_spec)
    try:
        while not host.should_stop():
            t0 = time.monotonic()
            host.step()
            remaining = host.idle_sleep() - (time.monotonic() - t0)
            if remaining > 0:
                time.sleep(remaining)
    except (BrokenPipeError, OSError):
        pass
    finally:
        host.stop()


def run_as_frontend(
    actor_source: "ActorSource",
    endpoint: TransportEndpoint,
    *,
    app_spec: AppSpec | None = None,
    runtime: AppRuntime | None = None,
) -> None:
    """Run a generic frontend client connected to an orchestrator endpoint.

    Headless/automated frontend loop. Qt/Vispy frontends use
    ``VispyFrontendHost`` directly (it owns the Qt event loop while still
    participating in the same orchestrator+spawn pattern).

    If ``app_spec`` is None the frontend stays in its loading state until the
    backend's AppSpecSnapshot arrives. If ``runtime`` is provided, the loop
    exits when ``runtime.is_stopped()``; otherwise it runs until the endpoint
    closes or KeyboardInterrupt.
    """
    from compneurovis.frontends.host import FrontendHost

    host = FrontendHost(endpoint=endpoint)
    host.start(actor_source, app_spec)
    try:
        while runtime is None or not runtime.is_stopped():
            t0 = time.monotonic()
            host.step()
            remaining = host.idle_sleep() - (time.monotonic() - t0)
            if remaining > 0:
                time.sleep(remaining)
    except (BrokenPipeError, OSError, KeyboardInterrupt):
        pass
    finally:
        host.stop()


__all__ = [
    "run_app",
    "run_orchestrator",
    "run_as_backend",
    "run_as_frontend",
    "start_app",
]
