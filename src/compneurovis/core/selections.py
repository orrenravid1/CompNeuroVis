"""Neutral selection declarations shared by authoring, runtimes, and frontends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from compneurovis.core._immutability import snapshot_message_data
from compneurovis.core.references import AppRef, app_ref
from compneurovis.core.specs import IdentifiedSpec


def selection_after_click(
    current: object,
    value: Any,
    *,
    multiple: bool,
) -> list[Any]:
    """Apply canonical single/multiple policy to one immutable selection value."""

    if current is None:
        selected: list[Any] = []
    elif isinstance(current, (str, bytes)):
        selected = [current]
    else:
        try:
            selected = list(current)  # type: ignore[arg-type]
        except TypeError:
            selected = [current]

    value = snapshot_message_data(value, path="selection click value")
    if not multiple:
        return [value]
    match = next(
        (index for index, item in enumerate(selected) if _values_equal(item, value)),
        None,
    )
    if match is not None:
        selected.pop(match)
    else:
        selected.append(value)
    return selected


def _values_equal(left: Any, right: Any) -> bool:
    """Compare immutable message values without assuming scalar ``==``."""

    try:
        result = left == right
    except Exception:
        return False
    if isinstance(result, bool):
        return result
    all_values = getattr(result, "all", None)
    if callable(all_values):
        try:
            return bool(all_values())
        except Exception:
            return False
    try:
        return bool(result)
    except (TypeError, ValueError):
        return False


@dataclass(frozen=True, slots=True)
class SelectionSpec(IdentifiedSpec):
    """Fragment-scoped selection state over an explicitly typed target."""

    target_type: Literal["geometry", "hit_target"] = "geometry"
    target_id: str | AppRef = ""
    item_kind: str = "entity"
    initial: tuple[Any, ...] = ()
    multiple: bool = False

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("SelectionSpec.id cannot be empty")
        if self.target_type not in ("geometry", "hit_target"):
            raise ValueError(
                "SelectionSpec.target_type must be 'geometry' or 'hit_target'"
            )
        if isinstance(self.target_id, str) and not self.target_id.strip():
            raise ValueError("SelectionSpec.target_id cannot be empty")
        item_kind = str(self.item_kind).strip()
        if not item_kind:
            raise ValueError("SelectionSpec.item_kind cannot be empty")
        if item_kind == "entity" and self.target_type != "geometry":
            raise ValueError("Entity selections require a geometry target")
        initial = tuple(
            snapshot_message_data(value, path="SelectionSpec.initial")
            for value in self.initial
        )
        if not self.multiple and len(initial) > 1:
            raise ValueError("A single SelectionSpec accepts at most one initial value")
        if any(
            _values_equal(value, previous)
            for index, value in enumerate(initial)
            for previous in initial[:index]
        ):
            raise ValueError("SelectionSpec.initial cannot contain duplicate values")
        object.__setattr__(
            self,
            "target_id",
            app_ref(self.target_id)
            if isinstance(self.target_id, AppRef)
            else str(self.target_id),
        )
        object.__setattr__(self, "item_kind", item_kind)
        object.__setattr__(self, "initial", initial)


__all__ = ["SelectionSpec", "selection_after_click"]
