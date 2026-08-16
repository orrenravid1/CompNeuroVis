from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from compneurovis.core.references import AppRef, app_ref
from compneurovis.core.specs import IdentifiedSpec
from compneurovis.core.values import freeze_binding_data


@dataclass(frozen=True, slots=True)
class PointerInteractionSpec(IdentifiedSpec):
    """Conditionally capture a pointer stream and resolve portable values.

    The hit target supplies only routing identity. ``result_kind`` asks the
    active visual for a data-only value at each hit; the built-in neutral
    ``hit`` value needs no domain scope, while ``entity`` resolves within an
    explicitly declared geometry. Capture, clicking, selection, highlighting,
    and camera presentation remain independent policies.
    """

    hit_target_id: str | AppRef
    result_kind: str = "hit"
    geometry_scope_id: str | AppRef | None = None
    enabled: Any = True
    button: Literal["primary", "secondary", "middle"] = "primary"

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("PointerInteractionSpec.id cannot be empty")
        if isinstance(self.hit_target_id, str) and not self.hit_target_id.strip():
            raise ValueError("PointerInteractionSpec.hit_target_id cannot be empty")
        result_kind = str(self.result_kind).strip()
        if not result_kind:
            raise ValueError("PointerInteractionSpec.result_kind cannot be empty")
        if (
            isinstance(self.geometry_scope_id, str)
            and not self.geometry_scope_id.strip()
        ):
            raise ValueError(
                "PointerInteractionSpec.geometry_scope_id cannot be empty"
            )
        if result_kind == "entity" and self.geometry_scope_id is None:
            raise ValueError("Entity pointer results require a geometry scope")
        object.__setattr__(
            self,
            "hit_target_id",
            app_ref(self.hit_target_id)
            if isinstance(self.hit_target_id, AppRef)
            else str(self.hit_target_id),
        )
        object.__setattr__(self, "result_kind", result_kind)
        if self.geometry_scope_id is not None:
            object.__setattr__(
                self,
                "geometry_scope_id",
                app_ref(self.geometry_scope_id)
                if isinstance(self.geometry_scope_id, AppRef)
                else str(self.geometry_scope_id),
            )
        object.__setattr__(
            self,
            "enabled",
            freeze_binding_data(
                self.enabled,
                path=f"PointerInteractionSpec[{self.id!r}].enabled",
            ),
        )
        if self.button not in ("primary", "secondary", "middle"):
            raise ValueError(
                "PointerInteractionSpec.button must be 'primary', 'secondary', "
                "or 'middle'"
            )


__all__ = ["PointerInteractionSpec"]
