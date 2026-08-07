from __future__ import annotations

import queue

from compneurovis.transports.pipe import PipeEndpoint, PipeEndpointPair


def make_inprocess_pair(*, left_name: str = "left", right_name: str = "right") -> PipeEndpointPair:
    left_inbound: queue.Queue = queue.Queue()
    right_inbound: queue.Queue = queue.Queue()
    return PipeEndpointPair(
        left=PipeEndpoint(inbound=left_inbound, outbound=right_inbound, mode="inprocess", name=left_name),
        right=PipeEndpoint(inbound=right_inbound, outbound=left_inbound, mode="inprocess", name=right_name),
    )


def inprocess_transport(id_a: str, id_b: str):
    """Bus transport factory for exactly two actors sharing one process.

    Use when both actors run in the same process (e.g., an in-process backend
    paired with a Qt frontend). For actors in separate processes, use
    pipe_transport instead.
    """
    def factory(actors, routing=None):
        actor_ids = {actor.id for actor in actors}
        expected = {id_a, id_b}
        if actor_ids != expected:
            raise ValueError(
                f"inprocess_transport expected actor ids {sorted(expected)}, "
                f"got {sorted(actor_ids)}"
            )
        from compneurovis.core.runtime.bus import bus_transport

        return bus_transport(mode="inprocess")(actors, routing)

    return factory


__all__ = ["inprocess_transport", "make_inprocess_pair"]
