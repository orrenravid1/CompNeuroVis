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
    if not callable(getattr(adapter, "resolve_field", None)):
        raise TypeError(
            f"Operator adapter {normalized!r} must provide callable resolve_field()"
        )
    for hook_name in (
        "affects_output",
        "output_field_deps",
        "output_binds_value",
    ):
        hook = getattr(adapter, hook_name, None)
        if hook is not None and not callable(hook):
            raise TypeError(
                f"Operator adapter {normalized!r} attribute {hook_name!r} "
                "must be callable when provided"
            )
    existing = _OPERATOR_ADAPTERS.get(normalized)
    if existing is not None and existing is not adapter:
        raise ValueError(f"Operator adapter {normalized!r} is already registered")
    _OPERATOR_ADAPTERS[normalized] = adapter


def operator_adapter(op: Any) -> Any:
    """Return an operator's adapter, failing clearly for authored operators."""
    kind = getattr(op, "kind", None)
    adapter = _OPERATOR_ADAPTERS.get(kind)
    if adapter is not None or kind is None:
        return adapter

    from compneurovis.core import OperatorSpec

    if isinstance(op, OperatorSpec):
        raise LookupError(
            f"No VisPy operator adapter is installed for operator kind {kind!r}. "
            "Register it in the widget's deferred VisPy callback."
        )
    return None


__all__ = [
    "OperatorResolveContext",
    "operator_adapter",
    "register_operator_adapter",
]
