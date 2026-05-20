"""Lower generic source authoring objects into concrete runtime launches."""

from __future__ import annotations

import inspect
import multiprocessing as mp
import os
from dataclasses import dataclass
from typing import Any, Protocol

from compneurovis.backends.base import BackendBase
from compneurovis.backends.host import ThreadBackendHost
from compneurovis.core.app import ActorRole, ActorSpec, AppSpec, MessageMatch, RouteSpec, RoutingSpec, RunSpec
from compneurovis.core.geometry import MorphologyGeometrySpec
from compneurovis.core.hosts import ActorProcess, ScriptBackendProcess, get_script_backend_channel
from compneurovis.core.messages import AppSpecDeclared, update_message


class InlineSourceProtocol(Protocol):
    """Minimal source contract needed to lower a source into a RunSpec."""

    def _make_backend(self) -> BackendBase: ...

    def _build_app_spec_for_backend(self, backend: BackendBase) -> AppSpec: ...

    def _notebook_dt(self) -> float: ...


@dataclass(slots=True)
class SourceRunPlan:
    """Source lowered to the runtime-neutral pieces shared by all launch modes."""

    backend: BackendBase
    app_spec: AppSpec
    routing: RoutingSpec
    notebook_dt: float


def build_source_run_plan(source: InlineSourceProtocol) -> SourceRunPlan:
    """Lower any source adapter to the backend actor plus startup AppSpec."""

    backend = source._make_backend()
    app_spec = source._build_app_spec_for_backend(backend)
    return SourceRunPlan(
        backend=backend,
        app_spec=app_spec,
        routing=build_source_routing(app_spec, backend_actor_id="backend", frontend_actor_ids=("frontend",)),
        notebook_dt=source._notebook_dt(),
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
    return RoutingSpec(
        routes=tuple(routes),
        default_targets={
            "command": backend_targets,
            "update": frontend_actor_ids,
        },
    )


def launch_source(source: InlineSourceProtocol) -> Any:
    """Launch a source using the active environment's default runtime profile."""

    channel = get_script_backend_channel()
    if channel is not None:
        run_source_backend(source, channel)
        return None

    if mp.current_process().name != "MainProcess":
        return None

    if _in_notebook():
        return launch_notebook_source(source)

    from compneurovis.core.run import run_app

    script_path = inspect.stack()[-1].filename
    run_app(build_desktop_run_spec(script_path))
    return None


def run_source_backend(source: InlineSourceProtocol, channel: Any) -> None:
    """Run the backend half of a source-launched app inside a script worker.

    Delegates to ``run_as_backend`` — the same primitive a remote backend
    worker would invoke. The script-rerun subprocess and a future remote
    backend follow the same code path (run_orchestrator + run_as_backend
    composition); only the launch mechanism differs.
    """
    from compneurovis.core.run import run_as_backend

    plan = build_source_run_plan(source)
    channel.send(update_message(AppSpecDeclared(plan.app_spec)))
    run_as_backend(lambda: plan.backend, channel, app_spec=plan.app_spec)


def build_desktop_run_spec(script_path: str) -> RunSpec:
    """Build the bundled desktop RunSpec for a source — without building it.

    The script worker is the startup source for this path because the main
    process intentionally avoids a duplicate model/geometry build. It declares
    the AppSpec through the runtime channel before running the backend actor;
    the backend actor itself is not the AppSpec authority.
    """

    from compneurovis.frontends.vispy.frontend import VispyFrontendWindow
    from compneurovis.frontends.vispy.host import VispyFrontendHost
    from compneurovis.core.bus import bus_transport

    routing = RoutingSpec()
    return RunSpec(
        app_spec=None,
        actors=[
            ActorSpec(
                id="backend",
                role=ActorRole.BACKEND,
                host_source=lambda r, ch, _sp=script_path: ScriptBackendProcess(_sp, ch),
            ),
            ActorSpec(
                id="frontend",
                role=ActorRole.FRONTEND,
                host_source=lambda r, ch: VispyFrontendHost(VispyFrontendWindow, r, ch),
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
        NotebookFrontendHost,
        NotebookMorphologyRenderActor,
        StoppableFrontendHost,
    )
    from compneurovis.core.bus import bus_transport

    use_render_process = _notebook_render_process_enabled(plan.app_spec)
    frontend_actor_ids = ("frontend", "renderer") if use_render_process else ("frontend",)
    routing = build_source_routing(
        plan.app_spec,
        backend_actor_id="backend",
        frontend_actor_ids=frontend_actor_ids,
    )
    actors = [
        ActorSpec(
            id="backend",
            role=ActorRole.BACKEND,
            host_source=lambda r, ch, _backend=plan.backend: ThreadBackendHost(lambda: _backend, r, ch),
        ),
        ActorSpec(
            id="frontend",
            role=ActorRole.FRONTEND,
            host_source=lambda r, ch, _dt=plan.notebook_dt, _external=use_render_process: NotebookFrontendHost(
                r,
                ch,
                dt=_dt,
                external_morphology_render=_external,
            ),
        ),
    ]
    if use_render_process:
        actors.append(
            ActorSpec(
                id="renderer",
                role=ActorRole.FRONTEND,
                host_source=lambda r, ch: ActorProcess(
                    actor_source=NotebookMorphologyRenderActor,
                    app_spec=r.app_spec,
                    channel=ch,
                    host_class=StoppableFrontendHost,
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
    "run_source_backend",
]
