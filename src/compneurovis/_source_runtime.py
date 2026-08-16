"""Lower generic source authoring objects into concrete runtime launches."""

from __future__ import annotations

import inspect
import multiprocessing as mp
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from compneurovis.backends.base import BackendBase
from compneurovis.core.runtime.actor import ActorBase, ExecutionGateActor
from compneurovis.core.app_fragment import (
    AppFragment,
    build_integrated_app_spec,
    tag_fragment_message,
)
from compneurovis.core.app_spec import AppFragmentSpec, AppSpec
from compneurovis.core.runtime.actor_launchers import (
    ScriptActorProcess,
    get_script_actor_channel,
    stage_bootstrap_script_payload,
    get_script_actor_stop_event,
)
from compneurovis.core.messages import AppSpecDeclared, Message, MessagePayload, update_message
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
        self.backend.handle(message)
        self._drain_backend()

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
            RouteSpec(match=MessageMatch(intent="command", message_type="camera_command"), targets=backend_targets),
            RouteSpec(match=MessageMatch(intent="command", message_type="reset"), targets=backend_targets),
        )
    )
    return tuple(routes)


def launch_source(source: InlineSourceProtocol) -> Any:
    """Launch a source using the active environment's default runtime profile."""

    channel = get_script_actor_channel()
    if channel is not None:
        run_source_actor(source, channel)
        return None

    if mp.current_process().name != "MainProcess":
        stage_bootstrap_script_payload("source", source)
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
        stage_bootstrap_script_payload("sources", source_tuple)
        return None

    if _in_notebook():
        return launch_notebook_sources(source_tuple)

    from compneurovis.core.runtime.run import run_app

    script_path = inspect.stack()[-1].filename
    run_app(build_desktop_run_spec(script_path))
    return None


def run_source_actor(
    source: InlineSourceProtocol,
    channel: Any,
    *,
    begin_gated: bool = False,
) -> None:
    """Run the source-owned actor inside a script worker.

    Delegates to ``run_actor`` — the same primitive a remote actor
    worker would invoke. The script-rerun subprocess and a future remote
    actor follow the same code path (run_orchestrator + run_actor
    composition); only the launch mechanism differs.
    """
    from compneurovis.core.runtime.run import run_actor

    plan = build_source_run_plan(source)
    channel.send(update_message(AppSpecDeclared(plan.app_spec)))
    backend = ExecutionGateActor(plan.backend) if begin_gated else plan.backend
    run_actor(
        lambda: backend,
        channel,
        app_spec=plan.app_spec,
        stop_event=get_script_actor_stop_event(),
    )


def run_sources_actor(sources: tuple[InlineSourceProtocol, ...], channel: Any) -> None:
    """Run multiple source-owned actors behind one script worker channel."""
    from compneurovis.core.runtime.run import run_actor

    plan = build_multi_source_run_plan(sources)
    channel.send(update_message(AppSpecDeclared(plan.app_spec)))
    run_actor(
        lambda: CompositeBackendActor(plan.fragments),
        channel,
        app_spec=plan.app_spec,
        stop_event=get_script_actor_stop_event(),
    )


def _reset_authoring_app_for_script_worker() -> None:
    from compneurovis.inline import _reset_authoring_app

    _reset_authoring_app()


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
                    before_run=_reset_authoring_app_for_script_worker,
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
    """Lower one source, then delegate notebook placement to its frontend."""
    from compneurovis.frontends.vispy.notebook.runtime import (
        build_source_run_spec as build_notebook_source_run_spec,
        start_notebook_app,
    )

    plan = build_source_run_plan(source)
    handle, widget = start_notebook_app(build_notebook_source_run_spec(plan))
    setattr(source, "_handle", handle)
    return widget


def launch_notebook_sources(sources: tuple[InlineSourceProtocol, ...]) -> Any:
    """Lower independent sources, then delegate notebook placement."""
    from compneurovis.frontends.vispy.notebook.runtime import (
        build_multi_source_run_spec as build_notebook_multi_source_run_spec,
        start_notebook_app,
    )

    plan = build_multi_source_run_plan(sources)
    handle, widget = start_notebook_app(
        build_notebook_multi_source_run_spec(plan)
    )
    for source in sources:
        setattr(source, "_handle", handle)
    return widget


def launch_notebook_source_process(builder: Callable[[], Any]) -> Any:
    """Build a source in a child and present it through the notebook frontend."""
    import cloudpickle

    from compneurovis.frontends.vispy.notebook.runtime import (
        build_builder_run_spec,
        start_notebook_app,
    )

    try:
        cloudpickle.dumps(builder)
    except Exception as exc:  # pragma: no cover - guidance path
        raise RuntimeError(
            "cnv.show(build) needs a cloudpickle-serializable builder. It likely "
            "captured a live model object (e.g. an h.Section) in its closure. "
            "Construct everything inside the builder and return the configured "
            "source; capture no live NEURON/Jaxley objects."
        ) from exc

    run_spec = build_builder_run_spec(
        builder,
        before_run=_reset_authoring_app_for_script_worker,
    )
    _handle, widget = start_notebook_app(run_spec)
    return widget
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
    "build_source_routing",
    "build_source_run_plan",
    "launch_notebook_source",
    "launch_notebook_sources",
    "launch_source",
    "launch_sources",
    "run_source_actor",
    "run_sources_actor",
]

