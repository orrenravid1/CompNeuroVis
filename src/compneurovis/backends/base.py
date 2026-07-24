from __future__ import annotations

from typing import Any

from compneurovis.core.actor import ActorBase


class BackendBase(ActorBase):
    """Base for every source backend.

    Provides the minimal interaction surface the shared
    ``BackendInteractionContext`` talks to, so any backend -- generic inline,
    NEURON, Jaxley -- gets a uniform ctx for free. Concrete backends override
    these with model-aware implementations; the defaults keep geometry-less
    sources (e.g. plain inline line/surface sources) working.
    """

    geometry: Any = None
    _series_sampler: Any = None  # set by backends that declare series; read via ctx.series_sampler


    def _dispatch_action(self, action_id: str, payload: dict[str, Any]) -> bool:
        del action_id, payload
        return False

    def _interaction_context(self):
        from compneurovis.backends.interaction import BackendInteractionContext

        return BackendInteractionContext(self)
