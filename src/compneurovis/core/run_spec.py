from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Mapping

from compneurovis.core._immutability import FrozenDict
from compneurovis.core.diagnostics import DiagnosticsSpec
from compneurovis.core.specs import IdentifiedSpec, SpecBase

if TYPE_CHECKING:
    from compneurovis.core.app_spec import AppSpec


@dataclass(frozen=True, slots=True)
class ActorSpec(IdentifiedSpec):
    host_source: Any = None  # ActorHostSource: Callable[[AppRuntime, Channel | None], Startable] | None
    runs_in_foreground: bool = False


@dataclass(frozen=True, slots=True)
class MessageMatch(SpecBase):
    """Generic message predicate used by RoutingSpec."""

    intent: Literal["command", "update"] | None = None
    message_type: str | None = None
    attrs: Mapping[str, Any] = field(default_factory=FrozenDict)
    tags: Mapping[str, Any] = field(default_factory=FrozenDict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "attrs", FrozenDict(self.attrs))
        object.__setattr__(self, "tags", FrozenDict(self.tags))


@dataclass(frozen=True, slots=True)
class RouteSpec(SpecBase):
    """One ordered routing rule."""

    match: MessageMatch
    targets: tuple[str, ...]

    def __post_init__(self) -> None:
        targets = tuple(self.targets)
        if not targets:
            raise ValueError("RouteSpec.targets cannot be empty")
        if any(not isinstance(target, str) or not target.strip() for target in targets):
            raise ValueError("RouteSpec targets must be non-empty actor-id strings")
        if len(set(targets)) != len(targets):
            raise ValueError("RouteSpec targets cannot contain duplicate actor ids")
        object.__setattr__(self, "targets", targets)


@dataclass(frozen=True, slots=True, init=False)
class RoutingSpec(SpecBase):
    """Ordered routing policy read by the Bus.

    Routing is generic: rules match message intent, registered message type
    name, optional message tags, and optional payload attributes. The Bus does not hardcode control,
    action, field, frame, frontend concepts, or default directions.
    """

    routes: tuple[RouteSpec, ...]

    def __init__(
        self,
        *,
        routes: tuple[RouteSpec, ...] | list[RouteSpec] = (),
    ) -> None:
        object.__setattr__(self, "routes", tuple(routes))


@dataclass(frozen=True, slots=True)
class RunSpec(SpecBase):
    app_spec: "AppSpec | None" = None
    actors: tuple[ActorSpec, ...] = field(default_factory=tuple)
    transport: Any | None = None  # TransportFactory: Callable[[list[ActorSpec], RoutingSpec | None], ...]
    routing: RoutingSpec | None = None
    diagnostics: DiagnosticsSpec | None = None

    def __post_init__(self) -> None:
        actors = tuple(self.actors)
        raw_actor_ids = tuple(actor.id for actor in actors)
        if any(not isinstance(actor_id, str) for actor_id in raw_actor_ids):
            raise TypeError("RunSpec actor ids must be strings")
        actor_ids = raw_actor_ids
        if any(not actor_id.strip() for actor_id in actor_ids):
            raise ValueError("RunSpec actor ids cannot be empty")
        if any(actor_id != actor_id.strip() for actor_id in actor_ids):
            raise ValueError("RunSpec actor ids cannot contain surrounding whitespace")
        if len(set(actor_ids)) != len(actor_ids):
            duplicates = sorted(
                actor_id for actor_id in set(actor_ids) if actor_ids.count(actor_id) > 1
            )
            raise ValueError(f"RunSpec actor ids must be unique: {', '.join(duplicates)}")
        if actors and self.transport is None:
            raise ValueError("RunSpec with actors requires an explicit transport factory")
        if self.transport is not None and not callable(self.transport):
            raise TypeError("RunSpec.transport must be a callable transport factory")
        if self.routing is not None:
            known = set(actor_ids)
            unknown = sorted(
                {
                    target
                    for route in self.routing.routes
                    for target in route.targets
                    if target not in known
                }
            )
            if unknown:
                raise ValueError(
                    f"RunSpec routes reference unknown actor ids: {', '.join(unknown)}"
                )
        object.__setattr__(self, "actors", actors)


__all__ = [
    "ActorSpec",
    "MessageMatch",
    "RouteSpec",
    "RoutingSpec",
    "RunSpec",
]
