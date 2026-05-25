from __future__ import annotations

from typing import Any

from compneurovis.backends import BackendBase
from compneurovis.core.actor import ActorSource
from compneurovis.core.app import ActorSpec, AppSpec, RunSpec
from compneurovis.core.bus import bus_transport
from compneurovis.frontends.vispy import VispyActorHost, VispyFrontendWindow
from compneurovis.core.hosts import ActorHost, ActorProcess


def build_jaxley_app(
    backend: ActorSource,
    app_spec: AppSpec,
    *,
    title: str | None = None,
    interaction_target: Any = None,
) -> RunSpec:
    """Build a live app backed by a JaxleyBackend subclass or backend factory."""

    if isinstance(backend, BackendBase):
        raise TypeError(
            "build_jaxley_app() requires a Backend subclass or top-level zero-argument factory. "
            "Do not pass an already-created backend instance."
        )
    _backend = backend
    _title = title
    _it = interaction_target
    return RunSpec(
        app_spec=app_spec,
        actors=[
            ActorSpec(
                id="backend",
                host_source=lambda runtime, ch: ActorProcess(
                    actor_source=_backend,
                    app_spec=runtime.app_spec,
                    channel=ch,
                    host_class=ActorHost,
                ),
            ),
            ActorSpec(
                id="frontend",
                host_source=lambda runtime, ch: VispyActorHost(
                    actor_source=lambda: VispyFrontendWindow(title=_title, interaction_target=_it),
                    runtime=runtime,
                    channel=ch,
                ),
            ),
        ],
        transport=bus_transport(mode="pipe"),
    )
