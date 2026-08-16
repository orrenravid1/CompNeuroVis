from __future__ import annotations

from dataclasses import dataclass

from compneurovis.core.pointer import HitRecord
from compneurovis.core.references import AppRef, app_ref
from compneurovis.core.specs import IdentifiedSpec, SpecBase


@dataclass(frozen=True, slots=True)
class HitValue(SpecBase):
    """Stable, role-independent value selected from one geometric hit."""

    primitive_id: str | int | None = None
    world_position: tuple[float, float, float] | None = None
    normal: tuple[float, float, float] | None = None
    depth: float | None = None

    @classmethod
    def from_record(cls, hit: HitRecord) -> "HitValue":
        if not isinstance(hit, HitRecord):
            raise TypeError("HitValue.from_record(...) expects a HitRecord")
        return cls(
            primitive_id=hit.primitive_id,
            world_position=hit.world_position,
            normal=hit.normal,
            depth=hit.depth,
        )


@dataclass(frozen=True, slots=True)
class ClickSpec(IdentifiedSpec):
    """A derived click over a hit target with an open result-value kind.

    ``result_kind='hit'`` selects the neutral :class:`HitValue`. Registered
    frontend visuals may expose other data-only resolutions such as ``entity``.
    ``geometry_scope_id`` names geometry only when a semantic result needs domain
    scope (notably entity ids). Selection is optional state policy layered over
    the click result.
    """

    hit_target_id: str | AppRef
    result_kind: str = "hit"
    geometry_scope_id: str | AppRef | None = None
    selection_id: str | AppRef | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("ClickSpec.id cannot be empty")
        if isinstance(self.hit_target_id, str) and not self.hit_target_id.strip():
            raise ValueError("ClickSpec.hit_target_id cannot be empty")
        result_kind = str(self.result_kind).strip()
        if not result_kind:
            raise ValueError("ClickSpec.result_kind cannot be empty")
        if isinstance(self.selection_id, str) and not self.selection_id.strip():
            raise ValueError("ClickSpec.selection_id cannot be empty")
        if (
            isinstance(self.geometry_scope_id, str)
            and not self.geometry_scope_id.strip()
        ):
            raise ValueError("ClickSpec.geometry_scope_id cannot be empty")
        if result_kind == "entity" and self.geometry_scope_id is None:
            raise ValueError("Entity click results require a geometry scope")
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
        if self.selection_id is not None:
            object.__setattr__(
                self,
                "selection_id",
                app_ref(self.selection_id)
                if isinstance(self.selection_id, AppRef)
                else str(self.selection_id),
            )


__all__ = ["ClickSpec", "HitValue"]
