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

    def __post_init__(self) -> None:
        object.__setattr__(self, "attrs", FrozenDict(self.attrs))


@dataclass(frozen=True, slots=True)
class RouteSpec(SpecBase):
    """One ordered routing rule."""

    match: MessageMatch
    targets: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "targets", tuple(self.targets))


@dataclass(frozen=True, slots=True, init=False)
class RoutingSpec(SpecBase):
    """Ordered routing policy read by the Bus.

    Routing is generic: rules match message intent, registered message type
    name, and optional payload attributes. The Bus does not hardcode control,
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
        object.__setattr__(self, "actors", tuple(self.actors))


__all__ = [
    "ActorSpec",
    "MessageMatch",
    "RouteSpec",
    "RoutingSpec",
    "RunSpec",
]
