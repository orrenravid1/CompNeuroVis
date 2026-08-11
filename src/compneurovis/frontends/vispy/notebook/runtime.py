"""Notebook-owned RunSpec construction and frontend placement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from compneurovis.core.run_spec import (
    ActorSpec,
    MessageMatch,
    RouteSpec,
    RoutingSpec,
    RunSpec,
)
from compneurovis.core.runtime.actor import ActorInstanceSource
from compneurovis.core.runtime.actor_host import ActorHost
from compneurovis.core.runtime.actor_launchers import (
    ActorProcess,
    BuilderActorProcess,
    ThreadActorLauncher,
    assert_spawn_picklable,
)
from compneurovis.core.runtime.bus import bus_transport

if TYPE_CHECKING:
    from compneurovis._source_runtime import MultiSourceRunPlan, SourceRunPlan


class _NotebookRendererHost(ActorHost):
    """Drain renderer input before doing an expensive raster pass.

    Generic channels use a small poll budget for peer fairness. A dedicated
    renderer process has only one actor, and limiting it to 16 updates per
    raster pass lets its bounded inbound queue fill and block the entire Bus.
    The frontend compacts the drained batch before applying it, so draining all
    currently ready canonical updates is both faster and semantically safe.
    """

    def __init__(self, channel) -> None:
        super().__init__(channel=channel)
        if hasattr(channel, "max_payloads_per_poll"):
            channel.max_payloads_per_poll = 2048
        if hasattr(channel, "max_poll_duration_s"):
            channel.max_poll_duration_s = 0.05


@dataclass(frozen=True, slots=True)
class NotebookRuntimeOptions:
    """Explicit notebook placement and presentation options.

    ``render_hz`` is the ceiling for registered per-panel service levels.
    Browser paint acknowledgements bound actual frame production.
    """

    backend_process: bool = False
    render_process: bool = True
    render_hz: float = 15.0
    panel_size: tuple[int, int] = (960, 540)
    max_inflight_frames: int = 3


@dataclass(frozen=True, slots=True)
class _NotebookRendererSource:
    render_hz: float
    panel_size: tuple[int, int]
    max_inflight_frames: int

    def __call__(self):
        # Import Qt/Vispy only after ActorProcess enters the renderer child.
        from compneurovis.frontends.vispy.notebook.renderer import (
            NotebookPanelRenderActor,
        )

        return NotebookPanelRenderActor(
            render_hz=self.render_hz,
            panel_size=self.panel_size,
            max_inflight_frames=self.max_inflight_frames,
        )


def _frontend_spec(options: NotebookRuntimeOptions) -> ActorSpec:
    def build_host(runtime, channel):
        # Keep RunSpec construction usable without importing Qt/Vispy. The
        # rendering stack belongs to the frontend actor that actually runs it.
        from compneurovis.frontends.vispy.notebook.host import NotebookActorHost

        return NotebookActorHost(
            runtime,
            channel,
            render_hz=options.render_hz,
            panel_size=options.panel_size,
            external_frames=options.render_process,
        )

    return ActorSpec(
        id="frontend",
        host_source=build_host,
    )


def _renderer_spec(options: NotebookRuntimeOptions) -> ActorSpec:
    actor_source = _NotebookRendererSource(
        render_hz=options.render_hz,
        panel_size=options.panel_size,
        max_inflight_frames=options.max_inflight_frames,
    )
    return ActorSpec(
        id="renderer",
        host_source=lambda runtime, channel: ActorProcess(
            actor_source=actor_source,
            app_spec=runtime.app_spec,
            channel=channel,
            host_class=_NotebookRendererHost,
            diagnostics=runtime.diagnostics,
        ),
    )


def _notebook_routing(
    routing: RoutingSpec,
    *,
    render_process: bool,
) -> RoutingSpec:
    if not render_process:
        return routing
    command_routes = tuple(
        route for route in routing.routes if route.match.intent == "command"
    )
    return RoutingSpec(
        routes=(
            RouteSpec(
                match=MessageMatch(
                    intent="command", message_type="frame_presented"
                ),
                targets=("renderer",),
            ),
            *command_routes,
            RouteSpec(
                match=MessageMatch(
                    intent="update", message_type="rendered_frame"
                ),
                targets=("frontend",),
            ),
            RouteSpec(
                match=MessageMatch(
                    intent="update", message_type="field_replace"
                ),
                targets=("renderer",),
            ),
            RouteSpec(
                match=MessageMatch(
                    intent="update", message_type="field_append"
                ),
                targets=("renderer",),
            ),
            RouteSpec(
                match=MessageMatch(
                    intent="update", message_type="app_spec_declared"
                ),
                targets=("frontend", "renderer"),
            ),
            RouteSpec(
                match=MessageMatch(intent="update"),
                targets=("frontend", "renderer"),
            ),
        )
    )


def build_source_run_spec(
    plan: SourceRunPlan,
    *,
    options: NotebookRuntimeOptions | None = None,
) -> RunSpec:
    """Place one already-lowered source behind the notebook frontend."""
    resolved = options or NotebookRuntimeOptions()
    backend_source = ActorInstanceSource(plan.backend)
    if resolved.backend_process:
        assert_spawn_picklable(
            backend_source,
            label="notebook backend actor source",
        )
    backend = ActorSpec(
        id="backend",
        host_source=(
            lambda runtime, channel: ActorProcess(
                actor_source=backend_source,
                app_spec=runtime.app_spec,
                channel=channel,
                diagnostics=runtime.diagnostics,
            )
            if resolved.backend_process
            else ThreadActorLauncher(backend_source, runtime, channel)
        ),
    )
    actors = [backend]
    if resolved.render_process:
        actors.append(_renderer_spec(resolved))
    # Spawn every child before NotebookActorHost initializes Qt/Vispy in the
    # kernel process. Starting a multiprocessing child after QApplication and
    # an OpenGL context exist can hang on Windows and is unsafe on macOS too.
    actors.append(_frontend_spec(resolved))
    return RunSpec(
        app_spec=plan.app_spec,
        actors=actors,
        transport=bus_transport(
            mode=(
                "mpqueue"
                if resolved.render_process
                else ("pipe" if resolved.backend_process else "inprocess")
            )
        ),
        routing=_notebook_routing(
            plan.routing, render_process=resolved.render_process
        ),
    )


def build_multi_source_run_spec(
    plan: MultiSourceRunPlan,
    *,
    options: NotebookRuntimeOptions | None = None,
) -> RunSpec:
    """Place independent source fragments behind one notebook frontend."""
    resolved = options or NotebookRuntimeOptions()
    backend_specs: list[ActorSpec] = []
    for fragment in plan.fragments:
        source = ActorInstanceSource(fragment.actor)
        if resolved.backend_process:
            assert_spawn_picklable(
                source,
                label=f"notebook backend actor source {fragment.actor_id!r}",
            )
        backend_specs.append(
            ActorSpec(
                id=fragment.actor_id,
                host_source=(
                    lambda runtime, channel, _source=source: ActorProcess(
                        actor_source=_source,
                        app_spec=runtime.app_spec,
                        channel=channel,
                        diagnostics=runtime.diagnostics,
                    )
                    if resolved.backend_process
                    else ThreadActorLauncher(_source, runtime, channel)
                ),
            )
        )
    actors = [*backend_specs]
    if resolved.render_process:
        actors.append(_renderer_spec(resolved))
    actors.append(_frontend_spec(resolved))
    return RunSpec(
        app_spec=plan.app_spec,
        actors=actors,
        transport=bus_transport(
            mode=(
                "mpqueue"
                if resolved.render_process
                else ("pipe" if resolved.backend_process else "inprocess")
            )
        ),
        routing=_notebook_routing(
            plan.routing, render_process=resolved.render_process
        ),
    )


def build_builder_run_spec(
    builder: Callable[[], Any],
    *,
    before_run: Callable[[], None] | None = None,
    options: NotebookRuntimeOptions | None = None,
) -> RunSpec:
    """Place a child-built simulator source behind the notebook frontend."""
    resolved = options or NotebookRuntimeOptions(backend_process=True)
    if not resolved.backend_process:
        raise ValueError(
            "A deferred notebook builder must run in a backend subprocess; "
            "use build_source_run_spec() for an already-built in-process source"
        )
    base_routing = RoutingSpec(
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
    actors = [
        ActorSpec(
            id="backend",
            host_source=lambda runtime, channel: BuilderActorProcess(
                builder,
                channel,
                before_run=before_run,
            ),
        ),
    ]
    if resolved.render_process:
        actors.append(_renderer_spec(resolved))
    actors.append(_frontend_spec(resolved))
    return RunSpec(
        app_spec=None,
        actors=actors,
        transport=bus_transport(
            mode="mpqueue" if resolved.render_process else "pipe"
        ),
        routing=_notebook_routing(
            base_routing, render_process=resolved.render_process
        ),
    )


def start_notebook_app(run_spec: RunSpec):
    """Start a notebook RunSpec and return its handle and root ipywidget."""
    from compneurovis.core.runtime.run import start_app

    handle = start_app(run_spec)
    if handle is None:  # pragma: no cover - guarded by main-process launch paths
        raise RuntimeError("Notebook apps must start in the kernel's main process")
    return handle, handle.widget("frontend")


__all__ = [
    "NotebookRuntimeOptions",
    "build_builder_run_spec",
    "build_multi_source_run_spec",
    "build_source_run_spec",
    "start_notebook_app",
]
