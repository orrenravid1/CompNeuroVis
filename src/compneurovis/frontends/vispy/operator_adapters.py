"""Registry of per-operator-kind frontend adapters.

An operator kind (e.g. a grid slice) registers one adapter -- its whole frontend
contract -- from its own module. The planner/frontend hold no operator-type
knowledge: they look the adapter up by ``op.kind`` and dispatch. A third-party
operator registers the same way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from compneurovis.core import AppRef


@dataclass(frozen=True, slots=True)
class OperatorResolveContext:
    """Neutral resources available while resolving one operator output field."""

    get_field: Callable[[str | AppRef], Any]
    get_geometry: Callable[[str | AppRef], Any]
    values: Mapping[Any, Any]
    fragment_id: str

    def field(self, ref: str | AppRef):
        return self.get_field(ref)

    def geometry(self, ref: str | AppRef):
        return self.get_geometry(ref)


# Maps neutral operator kind → adapter. An adapter exposes any of:
#   output metadata: ``affects_output(changed_props)``, ``output_field_deps(op, frag)``,
#       ``output_binds_value(op, value_key, frag)``;
#   data resolution: ``resolve_field(op, OperatorResolveContext)`` → the
#       operator's computed output Field.
_OPERATOR_ADAPTERS: "dict[str, Any]" = {}


def register_operator_adapter(kind: str, adapter: Any) -> None:
    """Register the frontend adapter for one canonical operator kind."""
    normalized = str(kind).strip()
    if not normalized:
        raise ValueError("Operator adapter kind cannot be empty")
    existing = _OPERATOR_ADAPTERS.get(normalized)
    if existing is not None and existing is not adapter:
        raise ValueError(f"Operator adapter {normalized!r} is already registered")
    _OPERATOR_ADAPTERS[normalized] = adapter


def operator_adapter(op: Any) -> Any:
    """The registered frontend adapter for an operator spec (or None)."""
    return _OPERATOR_ADAPTERS.get(getattr(op, "kind", None))


__all__ = [
    "OperatorResolveContext",
    "operator_adapter",
    "register_operator_adapter",
]
