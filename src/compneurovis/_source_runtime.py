"""Lower generic source authoring objects into concrete runtime launches."""

from __future__ import annotations

import inspect
import multiprocessing as mp
import os
from dataclasses import dataclass
from typing import Any, Protocol

from compneurovis.backends.base import BackendBase
from compneurovis.core.app import ActorSpec, AppSpec, MessageMatch, RouteSpec, RoutingSpec, RunSpec
from compneurovis.core.geometry import MorphologyGeometrySpec
from compneurovis.core.actor_launchers import (
    ActorProcess,
    ScriptActorProcess,
    ThreadActorHost,
    get_script_actor_channel,
)
from compneurovis.core.messages import AppSpecDeclared, update_message


class InlineSourceProtocol(Protocol):
    """Minimal source contract needed to lower a source into a RunSpec."""

    def _make_backend(self) -> BackendBase: ...

    def _build_app_spec_for_backend(self, backend: BackendBase) -> AppSpec: ...


@dataclass(slots=True)
class SourceRunPlan:
    """Source lowered to the runtime-neutral pieces shared by all launch modes."""

    backend: BackendBase
    app_spec: AppSpec
    routing: RoutingSpec


def build_source_run_plan(source: InlineSourceProtocol) -> SourceRunPlan:
    """Lower any source adapter to the backend actor plus startup AppSpec."""

    backend = source._make_backend()
    app_spec = source._build_app_spec_for_backend(backend)
    return SourceRunPlan(
        backend=backend,
        app_spec=app_spec,
        routing=build_source_routing(app_spec, backend_actor_id="backend", frontend_actor_ids=("frontend",)),
    )


def build_source_routing(
    app_spec: AppSpec,
    *,
    backend_actor_id: str,
    frontend_actor_ids: tuple[str, ...],
) -> RoutingSpec:
    """Compile source-owned interactions to runtime actor routes."""

    backend_targets = (backend_actor_id,)
    routes: list[RouteSpec] = []
    for control_id, control in app_spec.interactions.controls.items():
        if control.send_to_backend:
            routes.append(
                RouteSpec(
                    match=MessageMatch(
                        intent="command",
                        message_type="set_control",
                        attrs={"control_id": control_id},
                    ),
                    targets=backend_targets,
                )
            )
    for action_id in app_spec.interactions.actions:
        routes.append(
            RouteSpec(
                match=MessageMatch(
                    intent="command",
                    message_type="invoke_action",
                    attrs={"action_id": action_id},
                ),
                targets=backend_targets,
            )
        )
    routes.extend(
        (
            RouteSpec(
                match=MessageMatch(intent="command"),
                targets=backend_targets,
            ),
            RouteSpec(
                match=MessageMatch(intent="update"),
                targets=frontend_actor_ids,
            ),
        )
    )
    return RoutingSpec(routes=tuple(routes))


def launch_source(source: InlineSourceProtocol) -> Any:
    """Launch a source using the active environment's default runtime profile."""

    channel = get_script_actor_channel()
    if channel is not None:
        run_source_actor(source, channel)
        return None

    if mp.current_process().name != "MainProcess":
        return None

    if _in_notebook():
        return launch_notebook_source(source)

    from compneurovis.core.run import run_app

    script_path = inspect.stack()[-1].filename
    run_app(build_desktop_run_spec(script_path))
    return None


def run_source_actor(source: InlineSourceProtocol, channel: Any) -> None:
    """Run the source-owned actor inside a script worker.

    Delegates to ``run_actor`` — the same primitive a remote actor
    worker would invoke. The script-rerun subprocess and a future remote
    actor follow the same code path (run_orchestrator + run_actor
    composition); only the launch mechanism differs.
    """
    from compneurovis.core.run import run_actor

    plan = build_source_run_plan(source)
    channel.send(update_message(AppSpecDeclared(plan.app_spec)))
    run_actor(lambda: plan.backend, channel, app_spec=plan.app_spec)


def build_desktop_run_spec(script_path: str) -> RunSpec:
    """Build the bundled desktop RunSpec for a source — without building it.

    The script worker is the startup source for this path because the main
    process intentionally avoids a duplicate model/geometry build. It declares
    the AppSpec through the runtime channel before running the backend actor;
    the backend actor itself is not the AppSpec authority.
    """

    from compneurovis.frontends.vispy.frontend import VispyFrontendWindow
    from compneurovis.frontends.vispy.host import VispyActorHost
    from compneurovis.core.bus import bus_transport

    routing = RoutingSpec(
        routes=(
            RouteSpec(
                match=MessageMatch(intent="command"),
                targets=("backend",),
            ),
            RouteSpec(
                match=MessageMatch(intent="update"),
                targets=("frontend",),
            ),
        )
    )
    return RunSpec(
        app_spec=None,
        actors=[
            ActorSpec(
                id="backend",
                host_source=lambda r, ch, _sp=script_path: ScriptActorProcess(_sp, ch),
            ),
            ActorSpec(
                id="frontend",
                host_source=lambda r, ch: VispyActorHost(VispyFrontendWindow, r, ch),
                runs_in_foreground=True,
            ),
        ],
        transport=bus_transport(mode="pipe"),
        routing=routing,
    )


def launch_notebook_source(source: InlineSourceProtocol) -> Any:
    """Build and start the in-process notebook RunSpec for a lowered source."""

    from compneurovis.core.run import start_app

    handle = start_app(build_notebook_run_spec(build_source_run_plan(source)))
    setattr(source, "_handle", handle)
    return handle.widget("frontend")


def build_notebook_run_spec(plan: SourceRunPlan) -> RunSpec:
    """Build the notebook RunSpec for a lowered source."""

    from compneurovis.frontends.vispy.notebook_host import (
        NotebookActorHost,
        NotebookMorphologyRenderActor,
    )
    from compneurovis.core.actor_host import ActorHost
    from compneurovis.core.bus import bus_transport

    use_render_process = _notebook_render_process_enabled(plan.app_spec)
    frontend_actor_ids = ("frontend", "renderer") if use_render_process else ("frontend",)
    routing = build_source_routing(
        plan.app_spec,
        backend_actor_id="backend",
        frontend_actor_ids=frontend_actor_ids,
    )
    notebook_dt = _notebook_dt_for_backend(plan.backend)

    def frontend_host_source(runtime, channel, *, _dt=notebook_dt, _external=use_render_process):
        return NotebookActorHost(
            runtime,
            channel,
            dt=_dt,
            external_morphology_render=_external,
        )

    actors = [
        ActorSpec(
            id="backend",
            host_source=lambda r, ch, _backend=plan.backend: ThreadActorHost(lambda: _backend, r, ch),
        ),
        ActorSpec(
            id="frontend",
            host_source=frontend_host_source,
        ),
    ]
    if use_render_process:
        actors.append(
            ActorSpec(
                id="renderer",
                host_source=lambda r, ch: ActorProcess(
                    actor_source=NotebookMorphologyRenderActor,
                    app_spec=r.app_spec,
                    channel=ch,
                    host_class=ActorHost,
                    diagnostics=r.diagnostics,
                ),
            )
        )

    return RunSpec(
        app_spec=plan.app_spec,
        actors=actors,
        transport=bus_transport(mode="pipe" if use_render_process else "inprocess"),
        routing=routing,
    )


def _notebook_dt_for_backend(backend: BackendBase) -> float:
    backend_dt = getattr(backend, "dt", None)
    if backend_dt is None:
        return 0.025
    return float(backend_dt)


def _notebook_render_process_enabled(app_spec: AppSpec) -> bool:
    enabled = os.environ.get("CNV_NOTEBOOK_RENDER_PROCESS", "").strip().lower()
    if enabled not in {"1", "true", "yes", "on"}:
        return False
    return any(isinstance(geometry, MorphologyGeometrySpec) for geometry in app_spec.data.geometries.values())


def _in_notebook() -> bool:
    try:
        from IPython import get_ipython
    except ModuleNotFoundError:
        return False
    shell = get_ipython()
    return shell is not None and getattr(shell, "kernel", None) is not None


__all__ = [
    "SourceRunPlan",
    "InlineSourceProtocol",
    "build_desktop_run_spec",
    "build_notebook_run_spec",
    "build_source_routing",
    "build_source_run_plan",
    "launch_notebook_source",
    "launch_source",
    "run_source_actor",
]
