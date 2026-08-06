"""Lower generic source authoring objects into concrete runtime launches."""

from __future__ import annotations

import inspect
import multiprocessing as mp
from dataclasses import dataclass
from functools import partial
from typing import Any, Callable, Protocol

from compneurovis.backends.base import BackendBase
from compneurovis.core.runtime.actor import ActorBase, ActorInstanceSource
from compneurovis.core.app_fragment import (
    AppFragment,
    build_integrated_app_spec,
    tag_fragment_message,
)
from compneurovis.core.app_spec import AppFragmentSpec, AppSpec
from compneurovis.core.runtime.actor_launchers import (
    ActorProcess,
    BuilderActorProcess,
    ScriptActorProcess,
    ThreadActorLauncher,
    assert_spawn_picklable,
    get_script_actor_channel,
)
from compneurovis.core.messages import AppSpecDeclared, Message, MessagePayload, update_message
from compneurovis.core.runtime.options import env_flag
from compneurovis.core.run_spec import ActorSpec, MessageMatch, RouteSpec, RoutingSpec, RunSpec


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


@dataclass(slots=True)
class MultiSourceRunPlan:
    """Multiple source fragments assembled into one app/runtime declaration."""

    fragments: tuple[AppFragment, ...]
    app_spec: AppSpec
    routing: RoutingSpec


class FragmentScopedBackendActor(ActorBase):
    """Adapter that tags backend messages with their fragment id."""

    def __init__(self, fragment_id: str, backend: BackendBase, local_app_spec: AppSpec) -> None:
        super().__init__()
        self.fragment_id = fragment_id
        self.backend = backend
        self.local_app_spec = local_app_spec

    def initialize(self, app_spec: AppSpec | None) -> None:
        del app_spec
        self.backend.initialize(self.local_app_spec)
        self._drain_backend()

    def handle(self, message: Message[MessagePayload]) -> None:
        tagged_fragment_id = message.tags.get("fragment_id")
        if tagged_fragment_id is not None and tagged_fragment_id != self.fragment_id:
            return
        local_message = self._normalize_local_command(message)
        self.backend.handle(local_message)
        self._drain_backend()

    def _normalize_local_command(self, message: Message[MessagePayload]) -> Message[MessagePayload]:
        from compneurovis.core.messages import InvokeAction, Reset, command_message

        if isinstance(message.payload, InvokeAction) and message.payload.action_id == "reset":
            return command_message(Reset(), tags=message.tags)
        return message

    def tick(self) -> None:
        self.backend.tick()
        self._drain_backend()

    def is_active(self) -> bool:
        return self.backend.is_active()

    def idle_sleep(self) -> float:
        return self.backend.idle_sleep()

    def shutdown(self) -> None:
        self.backend.shutdown()

    def _drain_backend(self) -> None:
        for message in self.backend.take_outbound_messages():
            self.emit(tag_fragment_message(message, self.fragment_id))


class CompositeBackendActor(ActorBase):
    """Single-process host for multiple source fragments in script-rerun mode."""

    def __init__(self, fragments: tuple[AppFragment, ...]) -> None:
        super().__init__()
        self._actors = tuple(fragment.actor for fragment in fragments)

    def initialize(self, app_spec: AppSpec | None) -> None:
        for actor in self._actors:
            actor.initialize(app_spec)
            self._drain(actor)

    def handle(self, message: Message[MessagePayload]) -> None:
        for actor in self._actors:
            actor.handle(message)
            self._drain(actor)

    def tick(self) -> None:
        for actor in self._actors:
            if actor.is_active():
                actor.tick()
                self._drain(actor)

    def is_active(self) -> bool:
        return any(actor.is_active() for actor in self._actors)

    def idle_sleep(self) -> float:
        sleeps = [actor.idle_sleep() for actor in self._actors]
        return min(sleeps) if sleeps else 1.0 / 60.0

    def shutdown(self) -> None:
        for actor in self._actors:
            actor.shutdown()

    def _drain(self, actor: ActorBase) -> None:
        for message in actor.take_outbound_messages():
            self.emit(message)


def build_source_run_plan(source: InlineSourceProtocol) -> SourceRunPlan:
    """Lower any source adapter to the backend actor plus startup AppSpec."""

    backend = source._make_backend()
    app_spec = source._build_app_spec_for_backend(backend)
    return SourceRunPlan(
        backend=backend,
        app_spec=app_spec,
        routing=build_source_routing(app_spec, backend_actor_id="backend", frontend_actor_ids=("frontend",)),
    )


def build_source_fragment(
    source: InlineSourceProtocol,
    *,
    index: int,
    fragment_id: str,
) -> AppFragment:
    backend = source._make_backend()
    local_app_spec = source._build_app_spec_for_backend(backend)
    resolved_fragment_id = fragment_id or f"source{index}"
    fragment_spec = AppFragmentSpec.from_app_spec(resolved_fragment_id, local_app_spec)
    actor = FragmentScopedBackendActor(resolved_fragment_id, backend, local_app_spec)
    return AppFragment(
        id=resolved_fragment_id,
        fragment_spec=fragment_spec,
        actor=actor,
        actor_id=f"backend_{index}",
    )


def build_multi_source_run_plan(sources: tuple[InlineSourceProtocol, ...]) -> MultiSourceRunPlan:
    if not sources:
        raise RuntimeError("Cannot build a multi-source run plan with no sources")
    fragments = tuple(
        build_source_fragment(source, index=index, fragment_id=f"source{index}")
        for index, source in enumerate(sources)
    )
    app_spec = build_integrated_app_spec(fragments, title=_merged_title(sources))
    return MultiSourceRunPlan(
        fragments=fragments,
        app_spec=app_spec,
        routing=build_multi_source_routing(fragments, frontend_actor_ids=("frontend",)),
    )


def _merged_title(sources: tuple[InlineSourceProtocol, ...]) -> str:
    titles = [str(getattr(source, "_app_title", None) or getattr(source, "title", "") or "") for source in sources]
    unique = tuple(dict.fromkeys(title for title in titles if title))
    return unique[0] if len(unique) == 1 else "CompNeuroVis"


def build_source_routing(
    app_spec: AppSpec,
    *,
    backend_actor_id: str,
    frontend_actor_ids: tuple[str, ...],
) -> RoutingSpec:
    """Compile source-owned interactions to runtime actor routes."""

    routes = [
        *_source_command_routes(app_spec, backend_actor_id=backend_actor_id),
        RouteSpec(match=MessageMatch(intent="update"), targets=frontend_actor_ids),
    ]
    return RoutingSpec(routes=tuple(routes))


def _source_command_routes(app_spec: AppSpec, *, backend_actor_id: str) -> tuple[RouteSpec, ...]:
    backend_targets = (backend_actor_id,)
    routes: list[RouteSpec] = []
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
    routes.append(RouteSpec(match=MessageMatch(intent="command"), targets=backend_targets))
    return tuple(routes)


def build_multi_source_routing(
    fragments: tuple[AppFragment, ...],
    *,
    frontend_actor_ids: tuple[str, ...],
) -> RoutingSpec:
    """Compile app-fragment ownership into runtime actor routes."""

    routes = [
        *_multi_source_command_routes(fragments),
        RouteSpec(match=MessageMatch(intent="update"), targets=frontend_actor_ids),
    ]
    return RoutingSpec(routes=tuple(routes))


def _multi_source_command_routes(fragments: tuple[AppFragment, ...]) -> tuple[RouteSpec, ...]:
    routes: list[RouteSpec] = []
    backend_targets = tuple(fragment.actor_id for fragment in fragments)
    for fragment in fragments:
        routes.append(
            RouteSpec(
                match=MessageMatch(intent="command", tags={"fragment_id": fragment.id}),
                targets=(fragment.actor_id,),
            )
        )
    routes.extend(
        (
            RouteSpec(match=MessageMatch(intent="command", message_type="key_pressed"), targets=backend_targets),
            RouteSpec(match=MessageMatch(intent="command", message_type="camera_command"), targets=backend_targets),
            RouteSpec(match=MessageMatch(intent="command", message_type="reset"), targets=backend_targets),
        )
    )
    return tuple(routes)


def _notebook_update_routes(*, morphology_process: bool, line_plot_process: bool) -> tuple[RouteSpec, ...]:
    if not morphology_process and not line_plot_process:
        return (RouteSpec(match=MessageMatch(intent="update"), targets=("frontend",)),)

    active_targets = ["frontend"]
    if morphology_process:
        active_targets.append("renderer")
    if line_plot_process:
        active_targets.append("line_plot_renderer")
    all_frontend_targets = tuple(active_targets)

    return (
        RouteSpec(
            match=MessageMatch(intent="update", message_type="field_replace"),
            targets=("renderer",) if morphology_process else ("frontend",),
        ),
        RouteSpec(
            match=MessageMatch(intent="update", message_type="field_append"),
            targets=("line_plot_renderer",) if line_plot_process else ("frontend",),
        ),
        RouteSpec(match=MessageMatch(intent="update", message_type="rendered_frame"), targets=("frontend",)),
        RouteSpec(match=MessageMatch(intent="update", message_type="app_spec_declared"), targets=all_frontend_targets),
        RouteSpec(match=MessageMatch(intent="update", message_type="error"), targets=("frontend",)),
        RouteSpec(match=MessageMatch(intent="update"), targets=all_frontend_targets),
    )

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

    from compneurovis.core.runtime.run import run_app

    script_path = inspect.stack()[-1].filename
    run_app(build_desktop_run_spec(script_path))
    return None


def launch_sources(sources: tuple[InlineSourceProtocol, ...] | list[InlineSourceProtocol]) -> Any:
    """Launch one app assembled from all currently declared sources."""

    source_tuple = tuple(sources)
    if len(source_tuple) == 1:
        return launch_source(source_tuple[0])

    channel = get_script_actor_channel()
    if channel is not None:
        run_sources_actor(source_tuple, channel)
        return None

    if mp.current_process().name != "MainProcess":
        return None

    if _in_notebook():
        return launch_notebook_sources(source_tuple)

    from compneurovis.core.runtime.run import run_app

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
    from compneurovis.core.runtime.run import run_actor

    plan = build_source_run_plan(source)
    channel.send(update_message(AppSpecDeclared(plan.app_spec)))
    run_actor(lambda: plan.backend, channel, app_spec=plan.app_spec)


def run_sources_actor(sources: tuple[InlineSourceProtocol, ...], channel: Any) -> None:
    """Run multiple source-owned actors behind one script worker channel."""
    from compneurovis.core.runtime.run import run_actor

    plan = build_multi_source_run_plan(sources)
    channel.send(update_message(AppSpecDeclared(plan.app_spec)))
    run_actor(lambda: CompositeBackendActor(plan.fragments), channel, app_spec=plan.app_spec)


def _reset_inline_session_for_script_worker() -> None:
    from compneurovis.inline import _reset_inline_session

    _reset_inline_session()


def build_desktop_run_spec(script_path: str) -> RunSpec:
    """Build the bundled desktop RunSpec for a source — without building it.

    The script worker is the startup source for this path because the main
    process intentionally avoids a duplicate model/geometry build. It declares
    the AppSpec through the runtime channel before running the backend actor;
    the backend actor itself is not the AppSpec authority.
    """

    from compneurovis.frontends.vispy.frontend import VispyFrontendWindow
    from compneurovis.frontends.vispy.host import VispyActorHost
    from compneurovis.core.runtime.bus import bus_transport

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
                host_source=lambda r, ch, _sp=script_path: ScriptActorProcess(
                    _sp,
                    ch,
                    before_run=_reset_inline_session_for_script_worker,
                ),
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

    from compneurovis.core.runtime.run import start_app

    handle = start_app(build_notebook_run_spec(build_source_run_plan(source)))
    setattr(source, "_handle", handle)
    return handle.widget("frontend")


def launch_notebook_sources(sources: tuple[InlineSourceProtocol, ...]) -> Any:
    """Build and start a notebook RunSpec assembled from multiple sources."""

    from compneurovis.core.runtime.run import start_app

    plan = build_multi_source_run_plan(sources)
    handle = start_app(build_notebook_multi_run_spec(plan))
    for source in sources:
        setattr(source, "_handle", handle)
    return handle.widget("frontend")


def launch_notebook_source_process(builder: Callable[[], Any], *, dt: float = 0.025) -> Any:
    """Launch a notebook source with the sim in its own process.

    The backend is built from ``builder`` in a child process. If
    ``CNV_NOTEBOOK_RENDER_PROCESS=1`` is set, trace rendering runs in a child
    process too. Morphology rendering also runs out of process unless
    ``CNV_NOTEBOOK_RFB=1`` asks the notebook frontend to own the local RFB canvas.
    The backend child declares the AppSpec over the channel once it has built the
    source, so the kernel never constructs live simulator objects.
    """
    import cloudpickle

    from compneurovis.core.runtime.run import start_app

    try:
        cloudpickle.dumps(builder)
    except Exception as exc:  # pragma: no cover - guidance path
        raise RuntimeError(
            "cnv.show(build) needs a cloudpickle-serializable builder. It likely "
            "captured a live model object (e.g. an h.Section) in its closure. "
            "Construct everything inside the builder and return the configured "
            "source; capture no live NEURON/Jaxley objects."
        ) from exc

    handle = start_app(build_notebook_process_run_spec(builder, dt=dt))
    return handle.widget("frontend")


def build_notebook_process_run_spec(builder: Callable[[], Any], *, dt: float = 0.025) -> RunSpec:
    """Build the split notebook RunSpec for a deferred source builder.

    The builder child declares AppSpecDeclared after constructing the source.
    The in-kernel frontend and optional render processes adopt that declared
    spec, so notebook mode can keep sim, morphology rendering, and trace
    rendering out of the kernel while the kernel owns only the widget/control
    surface.
    """
    from compneurovis.frontends.vispy.notebook.host import (
        NotebookActorHost,
        NotebookMorphologyRenderActor,
        NotebookLinePlotRenderActor,
    )
    from compneurovis.core.runtime.actor_host import ActorHost
    from compneurovis.core.runtime.bus import bus_transport

    use_render_process = env_flag("CNV_NOTEBOOK_RENDER_PROCESS")
    use_morphology_process = use_render_process and not env_flag("CNV_NOTEBOOK_RFB")
    use_line_plot_process = use_render_process
    use_aux_process = use_morphology_process or use_line_plot_process
    routing = RoutingSpec(
        routes=(
            RouteSpec(match=MessageMatch(intent="command"), targets=("backend",)),
            *_notebook_update_routes(
                morphology_process=use_morphology_process,
                line_plot_process=use_line_plot_process,
            ),
        )
    )
    actors = [
        ActorSpec(
            id="backend",
            host_source=lambda r, ch, _b=builder: BuilderActorProcess(
                _b, ch, before_run=_reset_inline_session_for_script_worker
            ),
        ),
        ActorSpec(
            id="frontend",
            host_source=lambda r, ch, _dt=dt: NotebookActorHost(
                r,
                ch,
                dt=_dt,
                external_morphology_render=use_morphology_process,
                external_line_plot_render=use_line_plot_process,
            ),
            runs_in_foreground=False,
        ),
    ]
    if use_morphology_process:
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
    if use_line_plot_process:
        actors.append(
            ActorSpec(
                id="line_plot_renderer",
                host_source=lambda r, ch, _dt=dt: ActorProcess(
                    actor_source=partial(NotebookLinePlotRenderActor, dt=_dt),
                    app_spec=r.app_spec,
                    channel=ch,
                    host_class=ActorHost,
                    diagnostics=r.diagnostics,
                ),
            )
        )
    return RunSpec(
        app_spec=None,
        actors=actors,
        transport=bus_transport(mode="mpqueue" if use_aux_process else "pipe"),
        routing=routing,
    )


def build_notebook_run_spec(plan: SourceRunPlan) -> RunSpec:
    """Build the notebook RunSpec for a lowered source."""

    from compneurovis.frontends.vispy.notebook.host import (
        NotebookActorHost,
        NotebookMorphologyRenderActor,
        NotebookLinePlotRenderActor,
    )
    from compneurovis.core.runtime.actor_host import ActorHost
    from compneurovis.core.runtime.bus import bus_transport

    use_backend_process = _notebook_backend_process_enabled()
    use_render_process = _notebook_render_process_enabled(plan.app_spec)
    use_morphology_process = use_render_process and not env_flag("CNV_NOTEBOOK_RFB")
    use_line_plot_process = use_render_process
    use_aux_process = use_morphology_process or use_line_plot_process
    routing = RoutingSpec(
        routes=(
            *_source_command_routes(plan.app_spec, backend_actor_id="backend"),
            *_notebook_update_routes(
                morphology_process=use_morphology_process,
                line_plot_process=use_line_plot_process,
            ),
        )
    )
    notebook_dt = _notebook_dt_for_backend(plan.backend)
    backend_source = ActorInstanceSource(plan.backend)
    if use_backend_process:
        assert_spawn_picklable(backend_source, label="notebook backend actor source")

    def frontend_host_source(runtime, channel, *, _dt=notebook_dt):
        return NotebookActorHost(
            runtime,
            channel,
            dt=_dt,
            external_morphology_render=use_morphology_process,
            external_line_plot_render=use_line_plot_process,
        )

    actors = [
        ActorSpec(
            id="backend",
            host_source=(
                lambda r, ch, _source=backend_source: ActorProcess(
                    actor_source=_source,
                    app_spec=r.app_spec,
                    channel=ch,
                    diagnostics=r.diagnostics,
                )
                if use_backend_process
                else ThreadActorLauncher(_source, r, ch)
            ),
        ),
        ActorSpec(
            id="frontend",
            host_source=frontend_host_source,
        ),
    ]
    if use_morphology_process:
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
    if use_line_plot_process:
        actors.append(
            ActorSpec(
                id="line_plot_renderer",
                host_source=lambda r, ch, _dt=notebook_dt: ActorProcess(
                    actor_source=partial(NotebookLinePlotRenderActor, dt=_dt),
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
        transport=bus_transport(mode="mpqueue" if use_aux_process else ("pipe" if use_backend_process else "inprocess")),
        routing=routing,
    )


def build_notebook_multi_run_spec(plan: MultiSourceRunPlan) -> RunSpec:
    """Build the notebook RunSpec for an assembled multi-source app."""

    from compneurovis.frontends.vispy.notebook.host import (
        NotebookActorHost,
        NotebookMorphologyRenderActor,
        NotebookLinePlotRenderActor,
    )
    from compneurovis.core.runtime.actor_host import ActorHost
    from compneurovis.core.runtime.bus import bus_transport

    use_backend_process = _notebook_backend_process_enabled()
    use_render_process = _notebook_render_process_enabled(plan.app_spec)
    use_morphology_process = use_render_process and not env_flag("CNV_NOTEBOOK_RFB")
    use_line_plot_process = use_render_process
    use_aux_process = use_morphology_process or use_line_plot_process
    routing = RoutingSpec(
        routes=(
            *_multi_source_command_routes(plan.fragments),
            *_notebook_update_routes(
                morphology_process=use_morphology_process,
                line_plot_process=use_line_plot_process,
            ),
        )
    )
    backend_sources = tuple(ActorInstanceSource(fragment.actor) for fragment in plan.fragments)
    if use_backend_process:
        for fragment, source in zip(plan.fragments, backend_sources):
            assert_spawn_picklable(source, label=f"notebook backend actor source {fragment.actor_id!r}")

    backend_dts = [
        getattr(getattr(fragment.actor, "backend", fragment.actor), "dt")
        for fragment in plan.fragments
        if hasattr(getattr(fragment.actor, "backend", fragment.actor), "dt")
    ]
    notebook_dt = min((float(dt) for dt in backend_dts), default=0.025)

    def frontend_host_source(runtime, channel, *, _dt=notebook_dt):
        return NotebookActorHost(
            runtime,
            channel,
            dt=_dt,
            external_morphology_render=use_morphology_process,
            external_line_plot_render=use_line_plot_process,
        )

    actors = []
    for fragment, backend_source in zip(plan.fragments, backend_sources):
        actors.append(
            ActorSpec(
                id=fragment.actor_id,
                host_source=(
                    lambda r, ch, _source=backend_source: ActorProcess(
                        actor_source=_source,
                        app_spec=r.app_spec,
                        channel=ch,
                        diagnostics=r.diagnostics,
                    )
                    if use_backend_process
                    else ThreadActorLauncher(_source, r, ch)
                ),
            )
        )
    actors.append(
        ActorSpec(
            id="frontend",
            host_source=frontend_host_source,
        )
    )
    if use_morphology_process:
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
    if use_line_plot_process:
        actors.append(
            ActorSpec(
                id="line_plot_renderer",
                host_source=lambda r, ch, _dt=notebook_dt: ActorProcess(
                    actor_source=partial(NotebookLinePlotRenderActor, dt=_dt),
                    app_spec=r.app_spec,
                    channel=ch,
                    host_class=ActorHost,
                    diagnostics=r.diagnostics,
                ),
            )
        )

    return RunSpec(
        app_spec=plan.app_spec,
        actors=tuple(actors),
        transport=bus_transport(mode="mpqueue" if use_aux_process else ("pipe" if use_backend_process else "inprocess")),
        routing=routing,
    )


def _notebook_dt_for_backend(backend: BackendBase) -> float:
    backend_dt = getattr(backend, "dt", None)
    if backend_dt is None:
        return 0.025
    return float(backend_dt)


def _notebook_render_process_enabled(app_spec: AppSpec) -> bool:
    del app_spec
    return env_flag("CNV_NOTEBOOK_RENDER_PROCESS")


def _notebook_backend_process_enabled() -> bool:
    return env_flag("CNV_NOTEBOOK_BACKEND_PROCESS")


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
    "build_notebook_multi_run_spec",
    "build_source_routing",
    "build_source_run_plan",
    "launch_notebook_source",
    "launch_notebook_sources",
    "launch_source",
    "launch_sources",
    "run_source_actor",
    "run_sources_actor",
]

