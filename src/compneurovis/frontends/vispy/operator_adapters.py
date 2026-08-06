"""Registry of per-operator-kind frontend adapters.

An operator kind (e.g. a grid slice) registers one adapter -- its whole frontend
contract -- from its own module. The planner/frontend hold no operator-type
knowledge: they look the adapter up by ``op.kind`` and dispatch. A third-party
operator registers the same way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from compneurovis.core import AppRef


@dataclass(frozen=True, slots=True)
class OperatorRefreshContext:
    """What an operator adapter needs to route a change to overlay targets.

    ``view_id`` is the plain id used to build ``RefreshTarget``s; ``view_ref`` is its
    scoped ``AppRef``. ``view`` is the reconstructed render-config of the view the
    operator is being tested against; ``op`` is the operator spec.
    """

    view_id: str | AppRef
    view: Any
    view_ref: AppRef
    op: Any
    op_ref: AppRef


# Maps operator spec TYPE → adapter. An adapter exposes any of:
#   refresh routing: ``on_value_change(ctx, value_key)``,
#       ``on_field_replace(ctx, field_ref)``, ``on_operator_patch(ctx, changed_props)``
#       (each → ``set[RefreshTarget]``);
#   output metadata: ``affects_output(changed_props)``, ``output_field_deps(op, frag)``,
#       ``output_binds_value(op, value_key, frag)``;
#   data resolution: ``resolve_field(op, get_field, values)`` → the operator's
#       computed output Field (``get_field(field_id)`` fetches a source field).
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
