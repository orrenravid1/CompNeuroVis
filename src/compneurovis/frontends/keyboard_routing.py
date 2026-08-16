from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from compneurovis.core.keyboard import KeySample, KeyShortcut, parse_shortcut
from compneurovis.core.references import AppRef


@dataclass(frozen=True, slots=True)
class KeyClaim:
    """One scoped semantic consumer of a keyboard stream."""

    owner: AppRef


@dataclass(frozen=True, slots=True)
class ShortcutBinding:
    """Portable shortcut strings attached to one scoped semantic action."""

    owner: AppRef
    shortcuts: tuple[str, ...]


class ShortcutRecognizer:
    """Match single-keystroke shortcuts against neutral keyboard samples.

    A shortcut may contain ordinary modifiers such as ``Ctrl+R`` or
    ``Ctrl+Shift+R``. Multi-step sequences are deliberately outside this
    alpha contract.
    """

    def __init__(self) -> None:
        self._cache: dict[str, KeyShortcut] = {}

    def claims_for(
        self,
        sample: KeySample,
        bindings: Iterable[ShortcutBinding],
    ) -> tuple[KeyClaim, ...]:
        if sample.phase != "press":
            return ()
        actual_key = sample.key.casefold()
        actual_modifiers = sample.modifiers
        claims: list[KeyClaim] = []
        for binding in bindings:
            if any(
                shortcut.key == actual_key
                and shortcut.modifiers == actual_modifiers
                for shortcut in (
                    self._parse(authored) for authored in binding.shortcuts
                )
            ):
                claims.append(KeyClaim(binding.owner))
        return tuple(claims)

    def _parse(self, authored: str) -> KeyShortcut:
        text = str(authored).strip()
        cached = self._cache.get(text)
        if cached is not None:
            return cached
        parsed = parse_shortcut(text)
        self._cache[text] = parsed
        return parsed


ClaimResolver = Callable[[KeySample], tuple[KeyClaim, ...]]
ClaimDispatcher = Callable[[KeyClaim, KeySample], None]


class KeyboardRouter:
    """Frontend-local ownership of neutral keyboard press/release streams.

    The router knows no GUI toolkit or backend. A press with no claims returns
    ``False`` so native focus and frontend defaults remain available. Claimed
    presses retain their scoped owners through release even if modifiers change.
    """

    def __init__(self) -> None:
        self._claims: dict[str, tuple[KeyClaim, ...]] = {}

    def route(
        self,
        sample: KeySample,
        *,
        resolve_claims: ClaimResolver,
        dispatch: ClaimDispatcher,
    ) -> bool:
        identity = sample.identity
        if sample.phase == "press":
            claims = self._claims.get(identity) if sample.repeat else None
            if claims is None:
                claims = tuple(resolve_claims(sample))
            if not claims:
                return False
            self._claims[identity] = claims
        else:
            claims = self._claims.pop(identity, ())
            if not claims:
                return False
        try:
            for claim in claims:
                dispatch(claim, sample)
        except Exception:
            self._claims.pop(identity, None)
            raise
        return True

    def clear(self) -> None:
        """Forget keys held when a frontend loses focus or shuts down."""
        self._claims.clear()


__all__ = [
    "KeyboardRouter",
    "KeyClaim",
    "ShortcutBinding",
    "ShortcutRecognizer",
]
