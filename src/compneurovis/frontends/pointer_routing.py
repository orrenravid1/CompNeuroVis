from __future__ import annotations

from dataclasses import dataclass, replace
import logging
from typing import Callable

from compneurovis.core.pointer import ClickGesture, PointerEvent
from compneurovis.core.references import AppRef


@dataclass(frozen=True, slots=True)
class ClickBinding:
    """One authored click and the value kind its visual must resolve."""

    owner: AppRef
    result_kind: str

    def __post_init__(self) -> None:
        kind = str(self.result_kind).strip()
        if not kind:
            raise ValueError("ClickBinding.result_kind cannot be empty")
        object.__setattr__(self, "result_kind", kind)


@dataclass(frozen=True, slots=True)
class PointerClaim:
    """One semantic interaction's exclusive ownership of a pointer stream."""

    owner: AppRef
    target_role: str
    result_kind: str = "hit"

    def __post_init__(self) -> None:
        role = str(self.target_role).strip()
        if not role:
            raise ValueError("PointerClaim.target_role cannot be empty")
        object.__setattr__(self, "target_role", role)
        kind = str(self.result_kind).strip()
        if not kind:
            raise ValueError("PointerClaim.result_kind cannot be empty")
        object.__setattr__(self, "result_kind", kind)


ClaimResolver = Callable[[PointerEvent], PointerClaim | None]
ClaimDispatcher = Callable[[PointerClaim, PointerEvent], None]
PointerObserver = Callable[[PointerEvent], None]
ObservationActivityCallback = Callable[[bool], None]
_logger = logging.getLogger(__name__)


class PointerObservationHub:
    """Frontend-local observation of portable pointer events.

    Observers do not claim input, mutate backend state, or replace the pointer
    router. Renderers use this sibling seam for transient presentation such as
    hover previews. Subscribing with ``needs_hits=True`` asks the owning surface
    to populate hit records for otherwise unclaimed movement.
    """

    def __init__(
        self,
        on_activity_changed: ObservationActivityCallback | None = None,
    ) -> None:
        self._next_token = 0
        self._observers: dict[int, tuple[PointerObserver, bool]] = {}
        self._on_activity_changed = on_activity_changed

    @property
    def active(self) -> bool:
        return bool(self._observers)

    @property
    def needs_hits(self) -> bool:
        return any(needs_hits for _observer, needs_hits in self._observers.values())

    def subscribe(
        self,
        observer: PointerObserver,
        *,
        needs_hits: bool = False,
    ) -> Callable[[], None]:
        if not callable(observer):
            raise TypeError("Pointer observer must be callable")
        token = self._next_token
        self._next_token += 1
        self._observers[token] = (observer, bool(needs_hits))
        self._notify_activity()

        def unsubscribe() -> None:
            if self._observers.pop(token, None) is not None:
                self._notify_activity()

        return unsubscribe

    def emit(self, event: PointerEvent) -> None:
        observer_failed = False
        for token, (observer, _needs_hits) in tuple(self._observers.items()):
            try:
                observer(event)
            except Exception:
                # An optional presentation observer must not interrupt canonical
                # click routing, captured gestures, or camera fallback. Disable a
                # broken observer after its first failure to avoid a log storm.
                self._observers.pop(token, None)
                observer_failed = True
                _logger.exception("Pointer observer failed and was disabled")
        if observer_failed:
            self._notify_activity()

    def _notify_activity(self) -> None:
        if self._on_activity_changed is not None:
            self._on_activity_changed(self.active)


@dataclass(frozen=True, slots=True)
class _PointerCapture:
    claim: PointerClaim
    last_event: PointerEvent


class PointerRouter:
    """Frontend-local ownership for independent pointer streams.

    The router is renderer-neutral and knows no camera or backend. Returning
    ``False`` leaves the event unclaimed so a frontend can apply its ordinary
    fallback behavior. A successful press owns only that pointer id until release
    or cancellation; other pointers remain independently routable.
    """

    def __init__(self) -> None:
        self._captures: dict[str, _PointerCapture] = {}

    def claim_for(self, pointer_id: str) -> PointerClaim | None:
        capture = self._captures.get(str(pointer_id))
        return None if capture is None else capture.claim

    def is_captured(self, pointer_id: str) -> bool:
        return self.claim_for(pointer_id) is not None

    def route(
        self,
        event: PointerEvent,
        *,
        resolve_claim: ClaimResolver,
        dispatch: ClaimDispatcher,
    ) -> bool:
        sample = event.sample
        pointer_id = sample.pointer_id
        if sample.phase == "press":
            previous = self._captures.pop(pointer_id, None)
            if previous is not None:
                cancelled = PointerEvent(
                    sample=replace(
                        previous.last_event.sample,
                        phase="cancel",
                        button=None,
                        buttons=(),
                    ),
                    hits=previous.last_event.hits,
                )
                dispatch(previous.claim, cancelled)
            claim = resolve_claim(event)
            if claim is None:
                return False
            self._captures[pointer_id] = _PointerCapture(claim, event)
        else:
            capture = self._captures.get(pointer_id)
            if capture is None:
                return False
            claim = capture.claim
            self._captures[pointer_id] = _PointerCapture(claim, event)

        try:
            dispatch(claim, event)
        except Exception:
            self._captures.pop(pointer_id, None)
            raise
        if sample.phase in ("release", "cancel"):
            self._captures.pop(pointer_id, None)
        return True

    def cancel_all(self, dispatch: ClaimDispatcher) -> None:
        captures = tuple(self._captures.items())
        self._captures.clear()
        for _pointer_id, capture in captures:
            dispatch(
                capture.claim,
                PointerEvent(
                    sample=replace(
                        capture.last_event.sample,
                        phase="cancel",
                        button=None,
                        buttons=(),
                    ),
                    hits=capture.last_event.hits,
                ),
            )


class ClickRecognizer:
    """Derive clicks while retaining the press event and its geometric hits."""

    def __init__(
        self,
        *,
        max_distance: float = 5.0,
        button: str = "primary",
    ) -> None:
        distance = float(max_distance)
        if distance < 0:
            raise ValueError("ClickRecognizer.max_distance must be non-negative")
        if button not in ("primary", "secondary", "middle"):
            raise ValueError("ClickRecognizer.button is not a supported pointer button")
        self._max_distance_squared = distance * distance
        self._button = button
        self._presses: dict[
            str,
            tuple[tuple[float, float], PointerEvent],
        ] = {}

    def cancel(self, pointer_id: str) -> None:
        self._presses.pop(str(pointer_id), None)

    def feed(self, event: PointerEvent) -> ClickGesture | None:
        sample = event.sample
        pointer_id = sample.pointer_id
        position = sample.local_position or sample.position
        if sample.phase == "press":
            if sample.button == self._button:
                self._presses[pointer_id] = (position, event)
            else:
                self.cancel(pointer_id)
            return None
        if sample.phase == "cancel":
            self.cancel(pointer_id)
            return None
        if sample.phase != "release":
            return None
        start = self._presses.pop(pointer_id, None)
        if start is None or sample.button != self._button:
            return None
        press_position, press_event = start
        dx = position[0] - press_position[0]
        dy = position[1] - press_position[1]
        if dx * dx + dy * dy > self._max_distance_squared:
            return None
        return ClickGesture(press=press_event, release=event)


__all__ = [
    "ClickBinding",
    "ClickGesture",
    "ClickRecognizer",
    "PointerClaim",
    "PointerObservationHub",
    "PointerRouter",
]
