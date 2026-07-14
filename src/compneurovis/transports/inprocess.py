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
    """TransportFactory for two actors that share the same process (queue.Queue).

    Use when both actors run in the same process (e.g., an in-process backend
    paired with a Qt frontend). For actors in separate processes, use
    pipe_transport instead.
    """
    def factory(actors, routing=None):
        del actors, routing
        pair = make_inprocess_pair(left_name=id_a, right_name=id_b)
        return {id_a: pair.left, id_b: pair.right}
    return factory


__all__ = ["inprocess_transport", "make_inprocess_pair"]
