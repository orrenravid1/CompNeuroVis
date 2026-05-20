"""Lower generic source authoring objects into concrete runtime launches."""

from __future__ import annotations

import inspect
import multiprocessing as mp
import os
from dataclasses import dataclass
from typing import Any, Protocol

from compneurovis.backends.base import BackendBase
from compneurovis.backends.host import ThreadBackendHost
from compneurovis.core.app import ActorRole, ActorSpec, AppSpec, RelaySpec, RunSpec
from compneurovis.core.geometry import MorphologyGeometrySpec
from compneurovis.core.hosts import ActorProcess, ScriptBackendProcess, get_script_backend_endpoint


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
    routing: RelaySpec
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
) -> RelaySpec:
    """Compile source-owned interactions to runtime actor routes."""

    backend_targets = (backend_actor_id,)
    return RelaySpec(
        control_routes={
            control_id: backend_targets
            for control_id, control in app_spec.interactions.controls.items()
            if control.send_to_backend
        },
        action_routes={
            action_id: backend_targets
            for action_id in app_spec.interactions.actions
        },
        default_command_targets=backend_targets,
        default_update_targets=frontend_actor_ids,
    )


def launch_source(source: InlineSourceProtocol) -> Any:
    """Launch a source using the active environment's default runtime profile."""

    endpoint = get_script_backend_endpoint()
    if endpoint is not None:
        run_source_backend(source, endpoint)
        return None

    if mp.current_process().name != "MainProcess":
        return None

    if _in_notebook():
        return launch_notebook_source(source)

    from compneurovis.core.run import run_app

    script_path = inspect.stack()[-1].filename
    run_app(build_desktop_run_spec(script_path))
    return None


def run_source_backend(source: InlineSourceProtocol, endpoint: Any) -> None:
    """Run the backend half of a source-launched app inside a script worker.

    Delegates to ``run_as_backend`` — the same primitive a remote backend
    worker would invoke. The script-rerun subprocess and a future remote
    backend follow the same code path (run_orchestrator + run_as_backend
    composition); only the launch mechanism differs.
    """
    from compneurovis.core.run import run_as_backend

    plan = build_source_run_plan(source)
    run_as_backend(lambda: plan.backend, endpoint, app_spec=plan.app_spec)


def build_desktop_run_spec(script_path: str) -> RunSpec:
    """Build the bundled desktop RunSpec for a source — without building it.

    The backend (ScriptBackendProcess, the re-run script) is authoritative for
    the AppSpec and announces it via AppSpecSnapshot. The main process no longer
    builds the model + geometry just to seed the frontend — that was a full
    duplicate build. ``RelaySpec()`` is empty: the routed transport falls back
    to role-based routing (backend<->frontend), correct for this 1B:1F path.
    """

    from compneurovis.frontends.vispy.frontend import VispyFrontendWindow
    from compneurovis.frontends.vispy.host import VispyFrontendHost
    from compneurovis.transports import routed_transport

    routing = RelaySpec()
    return RunSpec(
        app_spec=None,
        actors=[
            ActorSpec(
                id="backend",
                role=ActorRole.BACKEND,
                host_source=lambda r, ep, _sp=script_path: ScriptBackendProcess(_sp, ep),
            ),
            ActorSpec(
                id="frontend",
                role=ActorRole.FRONTEND,
                host_source=lambda r, ep: VispyFrontendHost(VispyFrontendWindow, r, ep),
                runs_in_foreground=True,
            ),
        ],
        transport=routed_transport(routing),
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
    from compneurovis.transports import routed_transport

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
            host_source=lambda r, ep, _backend=plan.backend: ThreadBackendHost(lambda: _backend, r, ep),
        ),
        ActorSpec(
            id="frontend",
            role=ActorRole.FRONTEND,
            host_source=lambda r, ep, _dt=plan.notebook_dt, _external=use_render_process: NotebookFrontendHost(
                r,
                ep,
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
                host_source=lambda r, ep: ActorProcess(
                    actor_source=NotebookMorphologyRenderActor,
                    app_spec=r.app_spec,
                    endpoint=ep,
                    host_class=StoppableFrontendHost,
                    diagnostics=r.diagnostics,
                ),
            )
        )

    return RunSpec(
        app_spec=plan.app_spec,
        actors=actors,
        transport=routed_transport(routing, mode="pipe" if use_render_process else "inprocess"),
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
