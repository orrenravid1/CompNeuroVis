from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Sequence, TypeAlias

from compneurovis.core.runtime.channel import Channel

if TYPE_CHECKING:
    from compneurovis.core.run_spec import ActorSpec, RoutingSpec
    from compneurovis.core.runtime.bus import BusFabric


TransportEndpoint: TypeAlias = Channel


class Transport(Protocol):
    """Factory that constructs the complete bus fabric for one run."""

    def __call__(
        self,
        actors: Sequence["ActorSpec"],
        routing: "RoutingSpec | None" = None,
    ) -> "BusFabric": ...

__all__ = ["Transport", "TransportEndpoint"]
