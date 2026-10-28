from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal

from compneurovis.core.specs import SpecBase


KeyPhase = Literal["press", "release"]
KeyModifier = Literal["alt", "control", "meta", "shift"]

_MODIFIER_ORDER: tuple[KeyModifier, ...] = (
    "control",
    "alt",
    "shift",
    "meta",
)

_MODIFIER_ALIASES: dict[str, KeyModifier] = {
    "alt": "alt",
    "option": "alt",
    "ctrl": "control",
    "control": "control",
    "cmd": "meta",
    "command": "meta",
    "meta": "meta",
    "super": "meta",
    "win": "meta",
    "windows": "meta",
    "shift": "shift",
}


def canonical_modifiers(values) -> tuple[KeyModifier, ...]:
    """Validate and order toolkit-neutral input modifiers."""
    modifiers = tuple(values)
    unsupported = tuple(
        modifier for modifier in modifiers if modifier not in _MODIFIER_ORDER
    )
    if unsupported:
        raise ValueError(f"Unsupported input modifiers {unsupported!r}")
    return tuple(
        modifier for modifier in _MODIFIER_ORDER if modifier in modifiers
    )


@dataclass(frozen=True, slots=True)
class KeyShortcut(SpecBase):
    """Canonical single-keystroke shortcut used by every frontend."""

    key: str
    modifiers: tuple[KeyModifier, ...] = ()

    def __post_init__(self) -> None:
        key = str(self.key).strip()
        if not key:
            raise ValueError("KeyShortcut.key cannot be empty")
        object.__setattr__(self, "key", key.casefold())
        object.__setattr__(self, "modifiers", canonical_modifiers(self.modifiers))


def parse_shortcut(authored: str) -> KeyShortcut:
    """Parse one portable shortcut such as ``R`` or ``Ctrl+Shift+R``."""
    text = str(authored).strip()
    if not text:
        raise ValueError("Hotkey shortcut cannot be empty")
    parts = tuple(part.strip() for part in text.split("+"))
    if any(not part for part in parts):
        raise ValueError(f"Hotkey shortcut {text!r} is not a single modified key")
    modifiers: list[KeyModifier] = []
    for token in parts[:-1]:
        modifier = _MODIFIER_ALIASES.get(token.casefold())
        if modifier is None:
            raise ValueError(
                f"Hotkey shortcut {text!r} has unsupported modifier {token!r}"
            )
        modifiers.append(modifier)
    key = parts[-1]
    if key.casefold() in _MODIFIER_ALIASES:
        raise ValueError(f"Hotkey shortcut {text!r} has no non-modifier key")
    return KeyShortcut(key=key, modifiers=tuple(modifiers))


def shortcut_signature(shortcut: str | KeyShortcut) -> str:
    """Return a compact canonical signature suitable for frontend adapters."""
    parsed = parse_shortcut(shortcut) if isinstance(shortcut, str) else shortcut
    return "+".join((*parsed.modifiers, parsed.key))


@dataclass(frozen=True, slots=True)
class KeySample(SpecBase):
    """One frontend-originated, toolkit-neutral keyboard observation.

    ``key`` is the logical key seen by the user, while ``physical_key`` may
    identify its hardware position when a frontend can provide one. Hotkeys
    use the logical key and canonical modifiers; tools that care about keyboard
    layout may opt into the physical identity later without changing this
    contract.
    """

    phase: KeyPhase
    key: str
    physical_key: str | None = None
    modifiers: tuple[KeyModifier, ...] = ()
    repeat: bool = False
    timestamp: float | None = None

    def __post_init__(self) -> None:
        if self.phase not in ("press", "release"):
            raise ValueError("KeySample.phase must be 'press' or 'release'")
        key = str(self.key).strip()
        if not key:
            raise ValueError("KeySample.key cannot be empty")
        object.__setattr__(self, "key", key)
        if self.physical_key is not None:
            physical_key = str(self.physical_key).strip()
            object.__setattr__(
                self,
                "physical_key",
                physical_key or None,
            )
        object.__setattr__(self, "modifiers", canonical_modifiers(self.modifiers))
        object.__setattr__(self, "repeat", bool(self.repeat))
        if self.timestamp is not None:
            timestamp = float(self.timestamp)
            if not math.isfinite(timestamp):
                raise ValueError("KeySample.timestamp must be finite")
            object.__setattr__(self, "timestamp", timestamp)

    @property
    def identity(self) -> str:
        """Frontend-local identity used to pair press and release samples."""
        return self.physical_key or self.key.casefold()


__all__ = [
    "KeyModifier",
    "KeyPhase",
    "KeySample",
    "KeyShortcut",
    "canonical_modifiers",
    "parse_shortcut",
    "shortcut_signature",
]
