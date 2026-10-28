from __future__ import annotations

from typing import Any

from compneurovis.core.messages import Clicked
from compneurovis.core.pointer import ClickGesture, PointerEvent, PointerSample


def clicked(interaction_id: str, value: Any) -> Clicked:
    press = PointerEvent(
        PointerSample(
            pointer_id="test-pointer",
            phase="press",
            position=(0.5, 0.5),
            button="primary",
            buttons=("primary",),
        )
    )
    release = PointerEvent(
        PointerSample(
            pointer_id="test-pointer",
            phase="release",
            position=(0.5, 0.5),
            button="primary",
        )
    )
    return Clicked(interaction_id, ClickGesture(press, release), value)


__all__ = ["clicked"]
