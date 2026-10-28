from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal

from compneurovis.core.keyboard import KeyModifier, canonical_modifiers
from compneurovis.core.specs import IdentifiedSpec, SpecBase


PointerPhase = Literal["press", "move", "release", "cancel"]
PointerType = Literal["mouse", "touch", "pen", "unknown"]
PointerButton = Literal["primary", "secondary", "middle"]


def _point2(value, *, path: str) -> tuple[float, float]:
    if len(value) != 2:
        raise ValueError(f"{path} must contain x and y")
    point = (float(value[0]), float(value[1]))
    if not all(math.isfinite(item) for item in point):
        raise ValueError(f"{path} must contain finite values")
    return point


def _point3(value, *, path: str) -> tuple[float, float, float]:
    if len(value) != 3:
        raise ValueError(f"{path} must contain x, y, and z")
    point = (float(value[0]), float(value[1]), float(value[2]))
    if not all(math.isfinite(item) for item in point):
        raise ValueError(f"{path} must contain finite values")
    return point


@dataclass(frozen=True, slots=True)
class HitTargetSpec(IdentifiedSpec):
    """Authored view role that a frontend may hit-test.

    The consuming view binds this identity to one renderer-local role. Domain
    resolution, click, selection, gesture, and presentation policy remain
    independent layers over the route.
    """

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("HitTargetSpec.id cannot be empty")


@dataclass(frozen=True, slots=True)
class HitRecord(SpecBase):
    """Renderer-neutral geometric result for one ordered pointer hit.

    ``target_role`` is local to the authored view. ``primitive_id`` identifies a
    renderer primitive and deliberately has no built-in entity meaning. A view
    implementation may resolve that primitive into zero or more domain concepts.
    """

    target_role: str
    primitive_id: str | int | None = None
    world_position: tuple[float, float, float] | None = None
    normal: tuple[float, float, float] | None = None
    depth: float | None = None

    def __post_init__(self) -> None:
        role = str(self.target_role).strip()
        if not role:
            raise ValueError("HitRecord.target_role cannot be empty")
        object.__setattr__(self, "target_role", role)
        if self.primitive_id is not None and not isinstance(
            self.primitive_id, (str, int)
        ):
            raise TypeError("HitRecord.primitive_id must be a string, integer, or None")
        if self.world_position is not None:
            object.__setattr__(
                self,
                "world_position",
                _point3(self.world_position, path="HitRecord.world_position"),
            )
        if self.normal is not None:
            object.__setattr__(
                self,
                "normal",
                _point3(self.normal, path="HitRecord.normal"),
            )
        if self.depth is not None:
            depth = float(self.depth)
            if not math.isfinite(depth):
                raise ValueError("HitRecord.depth must be finite")
            object.__setattr__(self, "depth", depth)


@dataclass(frozen=True, slots=True)
class PointerSample(SpecBase):
    """One frontend-originated, renderer-neutral pointer observation.

    ``position`` and ``delta`` use normalized panel coordinates. Optional
    ``local_position`` and ``local_delta`` use frontend logical pixels and allow
    presentation-scale gesture thresholds without leaking a GUI toolkit type.
    """

    pointer_id: str
    phase: PointerPhase
    position: tuple[float, float]
    delta: tuple[float, float] = (0.0, 0.0)
    local_position: tuple[float, float] | None = None
    local_delta: tuple[float, float] | None = None
    pointer_type: PointerType = "unknown"
    button: PointerButton | None = None
    buttons: tuple[PointerButton, ...] = ()
    modifiers: tuple[KeyModifier, ...] = ()
    timestamp: float | None = None
    pressure: float | None = None

    def __post_init__(self) -> None:
        pointer_id = str(self.pointer_id).strip()
        if not pointer_id:
            raise ValueError("PointerSample.pointer_id cannot be empty")
        object.__setattr__(self, "pointer_id", pointer_id)
        if self.phase not in ("press", "move", "release", "cancel"):
            raise ValueError(
                "PointerSample.phase must be 'press', 'move', 'release', or 'cancel'"
            )
        if self.pointer_type not in ("mouse", "touch", "pen", "unknown"):
            raise ValueError(
                "PointerSample.pointer_type must be 'mouse', 'touch', 'pen', or 'unknown'"
            )
        object.__setattr__(
            self,
            "position",
            _point2(self.position, path="PointerSample.position"),
        )
        object.__setattr__(
            self,
            "delta",
            _point2(self.delta, path="PointerSample.delta"),
        )
        if self.local_position is not None:
            object.__setattr__(
                self,
                "local_position",
                _point2(
                    self.local_position,
                    path="PointerSample.local_position",
                ),
            )
        if self.local_delta is not None:
            object.__setattr__(
                self,
                "local_delta",
                _point2(self.local_delta, path="PointerSample.local_delta"),
            )
        if self.button is not None and self.button not in (
            "primary",
            "secondary",
            "middle",
        ):
            raise ValueError("PointerSample.button is not a supported pointer button")
        buttons = tuple(self.buttons)
        if any(
            button not in ("primary", "secondary", "middle")
            for button in buttons
        ):
            raise ValueError("PointerSample.buttons contains an unsupported button")
        object.__setattr__(self, "buttons", buttons)
        object.__setattr__(self, "modifiers", canonical_modifiers(self.modifiers))
        if self.timestamp is not None:
            timestamp = float(self.timestamp)
            if not math.isfinite(timestamp):
                raise ValueError("PointerSample.timestamp must be finite")
            object.__setattr__(self, "timestamp", timestamp)
        if self.pressure is not None:
            pressure = float(self.pressure)
            if not math.isfinite(pressure) or pressure < 0.0:
                raise ValueError("PointerSample.pressure must be non-negative and finite")
            object.__setattr__(self, "pressure", pressure)


@dataclass(frozen=True, slots=True)
class PointerEvent(SpecBase):
    """A pointer sample plus the ordered geometric hits at that sample."""

    sample: PointerSample
    hits: tuple[HitRecord, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.sample, PointerSample):
            raise TypeError("PointerEvent.sample must be a PointerSample")
        hits = tuple(self.hits)
        if any(not isinstance(hit, HitRecord) for hit in hits):
            raise TypeError("PointerEvent.hits must contain only HitRecord values")
        object.__setattr__(self, "hits", hits)

    def hit_for(self, target_role: str) -> HitRecord | None:
        return next(
            (hit for hit in self.hits if hit.target_role == target_role),
            None,
        )


@dataclass(frozen=True, slots=True)
class ClickGesture(SpecBase):
    """A click derived from one stable press origin and nearby release."""

    press: PointerEvent
    release: PointerEvent

    def __post_init__(self) -> None:
        if not isinstance(self.press, PointerEvent):
            raise TypeError("ClickGesture.press must be a PointerEvent")
        if not isinstance(self.release, PointerEvent):
            raise TypeError("ClickGesture.release must be a PointerEvent")
        if self.press.sample.phase != "press":
            raise ValueError("ClickGesture.press must contain a press sample")
        if self.release.sample.phase != "release":
            raise ValueError("ClickGesture.release must contain a release sample")
        if self.press.sample.pointer_id != self.release.sample.pointer_id:
            raise ValueError("ClickGesture events must use the same pointer id")


__all__ = [
    "HitRecord",
    "HitTargetSpec",
    "ClickGesture",
    "PointerButton",
    "PointerEvent",
    "PointerPhase",
    "PointerSample",
    "PointerType",
]
