from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from typing import Any


def _rebuild_spec(
    spec_type: type["SpecBase"],
    values: tuple[tuple[str, Any], ...],
) -> "SpecBase":
    """Reconstruct a spec through its public initializer after serialization."""

    return spec_type(**dict(values))


class SpecBase:
    """Marker for immutable declarative blueprint values."""

    def __reduce__(self):
        """Re-run spec validation/freezing when an actor unpickles a spec.

        NumPy does not preserve an array's read-only flag through pickle.  Specs
        therefore reconstruct through their initializer instead of accepting
        pickle's default direct slot restoration.
        """

        if not is_dataclass(self):
            raise TypeError(
                f"{type(self).__module__}.{type(self).__qualname__} must be a "
                "frozen dataclass to be serialized as a canonical spec"
            )
        values = tuple(
            (item.name, getattr(self, item.name))
            for item in fields(self)
            if item.init
        )
        return (_rebuild_spec, (type(self), values))


@dataclass(frozen=True, slots=True)
class IdentifiedSpec(SpecBase):
    """Base for immutable specs addressed by a stable id."""

    id: str


# Panel kinds — the frontend panel category a view declares itself for. Defined
# here (not in app_spec) so views.py can import them without an import cycle, and
# so a view's declared kind is validated uniformly rather than by isinstance.
PANEL_KIND_STANDALONE = "standalone"


__all__ = [
    "IdentifiedSpec",
    "SpecBase",
    "PANEL_KIND_STANDALONE",
]
