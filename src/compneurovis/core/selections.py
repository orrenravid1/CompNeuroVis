"""Neutral selection declarations shared by authoring, runtimes, and frontends."""

from __future__ import annotations

from dataclasses import dataclass

from compneurovis.core.references import AppRef
from compneurovis.core.specs import IdentifiedSpec


def selection_after_click(
    current: object,
    entity_id: str,
    *,
    multiple: bool,
) -> list[str]:
    """Apply the canonical single/multiple selection policy for one entity click."""

    if current is None:
        selected: list[str] = []
    elif isinstance(current, (str, bytes)):
        selected = [str(current)]
    else:
        try:
            selected = [str(value) for value in current]  # type: ignore[union-attr]
        except TypeError:
            selected = [str(current)]

    entity_id = str(entity_id)
    if not multiple:
        return [entity_id]
    without_clicked = [value for value in selected if value != entity_id]
    if len(without_clicked) == len(selected):
        without_clicked.append(entity_id)
    return without_clicked


@dataclass(frozen=True, slots=True)
class SelectionSpec(IdentifiedSpec):
    """Fragment-scoped entity-selection state associated with one geometry."""

    geometry_id: str | AppRef = ""
    initial: tuple[str, ...] = ()
    multiple: bool = False

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("SelectionSpec.id cannot be empty")
        if isinstance(self.geometry_id, str) and not self.geometry_id.strip():
            raise ValueError("SelectionSpec.geometry_id cannot be empty")
        initial = tuple(str(entity_id) for entity_id in self.initial)
        if not self.multiple and len(initial) > 1:
            raise ValueError(
                "A single SelectionSpec accepts at most one initial entity"
            )
        if len(set(initial)) != len(initial):
            raise ValueError(
                "SelectionSpec.initial cannot contain duplicate entity ids"
            )
        object.__setattr__(self, "initial", initial)


__all__ = ["SelectionSpec", "selection_after_click"]
