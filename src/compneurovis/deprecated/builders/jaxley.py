from __future__ import annotations

from typing import Any

from compneurovis.backends import BackendBase
from compneurovis.backends.host import BackendHost
from compneurovis.core.actor import ActorRole, ActorSource
from compneurovis.core.app import ActorSpec, AppSpec, RunSpec
from compneurovis.frontends.vispy import VispyFrontendHost, VispyFrontendWindow
from compneurovis.core.hosts import ActorProcess
from compneurovis.transports import pipe_transport


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
                role=ActorRole.BACKEND,
                host_source=lambda app_spec, ch: ActorProcess(
                    actor_source=_backend,
                    app_spec=app_spec,
                    channel=ch,
                    host_class=BackendHost,
                ),
            ),
            ActorSpec(
                id="frontend",
                role=ActorRole.FRONTEND,
                host_source=lambda app_spec, ch: VispyFrontendHost(
                    actor_source=lambda: VispyFrontendWindow(title=_title, interaction_target=_it),
                    app_spec=app_spec,
                    channel=ch,
                ),
            ),
        ],
        transport=pipe_transport("backend", "frontend"),
    )
