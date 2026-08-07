from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from compneurovis.core._immutability import FrozenDict, freeze_spec_data
from compneurovis.core.references import validate_local_id
from compneurovis.core.specs import SpecBase


@dataclass(frozen=True, slots=True)
class ValueBindingSpec(SpecBase):
    """Reference a value in an actor-local binding namespace."""

    key: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "key",
            validate_local_id(self.key, path="ValueBindingSpec.key"),
        )


def freeze_binding_data(value: Any, *, path: str) -> Any:
    """Recursively freeze language-neutral data that may contain bindings."""

    if isinstance(value, ValueBindingSpec):
        return (
            value
            if type(value) is ValueBindingSpec
            else ValueBindingSpec(key=str(value.key))
        )
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise TypeError(f"{path} keys must be non-empty strings")
            frozen[key] = freeze_binding_data(item, path=f"{path}.{key}")
        return FrozenDict(frozen)
    if isinstance(value, (tuple, list)):
        return tuple(
            freeze_binding_data(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    return freeze_spec_data(value, path=path)


__all__ = ["ValueBindingSpec", "freeze_binding_data"]

