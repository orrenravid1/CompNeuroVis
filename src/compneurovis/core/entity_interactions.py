from __future__ import annotations

from dataclasses import dataclass

from compneurovis.core.references import AppRef, app_ref
from compneurovis.core.specs import IdentifiedSpec


@dataclass(frozen=True, slots=True)
class EntityClickSpec(IdentifiedSpec):
    """A geometry-scoped click interaction with optional selection behavior.

    Clicking and selecting are deliberately separate concepts. A backend may
    consume this interaction for an editor tool or another authored behavior.
    When ``selection_id`` is present and the click is not consumed, the shared
    backend policy applies that selection's single/multiple toggle semantics.
    """

    geometry_id: str | AppRef
    selection_id: str | AppRef | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("EntityClickSpec.id cannot be empty")
        if isinstance(self.geometry_id, str) and not self.geometry_id.strip():
            raise ValueError("EntityClickSpec.geometry_id cannot be empty")
        if isinstance(self.selection_id, str) and not self.selection_id.strip():
            raise ValueError("EntityClickSpec.selection_id cannot be empty")
        object.__setattr__(
            self,
            "geometry_id",
            app_ref(self.geometry_id)
            if isinstance(self.geometry_id, AppRef)
            else str(self.geometry_id),
        )
        if self.selection_id is not None:
            object.__setattr__(
                self,
                "selection_id",
                app_ref(self.selection_id)
                if isinstance(self.selection_id, AppRef)
                else str(self.selection_id),
            )


__all__ = ["EntityClickSpec"]
