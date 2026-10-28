from __future__ import annotations

from compneurovis.core import AppRef, KeySample
from compneurovis.core.keyboard import parse_shortcut
from compneurovis.frontends.keyboard_routing import (
    KeyboardRouter,
    KeyClaim,
    ShortcutBinding,
    ShortcutRecognizer,
)


def test_modified_and_unmodified_shortcuts_are_distinct():
    recognizer = ShortcutRecognizer()
    bindings = (
        ShortcutBinding(AppRef("plain"), ("R",)),
        ShortcutBinding(AppRef("controlled"), ("Ctrl+R",)),
    )

    assert recognizer.claims_for(
        KeySample(phase="press", key="r"), bindings
    ) == (KeyClaim(AppRef("plain")),)
    assert recognizer.claims_for(
        KeySample(phase="press", key="R", modifiers=("control",)), bindings
    ) == (KeyClaim(AppRef("controlled")),)


def test_shortcut_parser_normalizes_portable_modifier_aliases():
    assert parse_shortcut("Control+Shift+r") == parse_shortcut("Ctrl+Shift+R")
    assert parse_shortcut("Command+R") == parse_shortcut("Meta+R")
    assert parse_shortcut("Option+R") == parse_shortcut("Alt+R")


def test_keyboard_router_preserves_claims_through_release():
    router = KeyboardRouter()
    claim = KeyClaim(AppRef("reset", "source"))
    observed = []

    assert router.route(
        KeySample(
            phase="press",
            key="R",
            physical_key="scan-19",
            modifiers=("control",),
        ),
        resolve_claims=lambda _sample: (claim,),
        dispatch=lambda *args: observed.append(args),
    )
    assert router.route(
        KeySample(
            phase="release",
            key="R",
            physical_key="scan-19",
        ),
        resolve_claims=lambda _sample: (),
        dispatch=lambda *args: observed.append(args),
    )
    assert [sample.phase for _, sample in observed] == ["press", "release"]


def test_keyboard_router_leaves_unclaimed_keys_to_frontend_fallback():
    router = KeyboardRouter()
    assert not router.route(
        KeySample(phase="press", key="F1"),
        resolve_claims=lambda _sample: (),
        dispatch=lambda *_args: None,
    )
