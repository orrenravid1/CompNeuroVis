from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from types import MappingProxyType
from typing import Any, Generic, TypeVar

import numpy as np

K = TypeVar("K")
V = TypeVar("V")


class FrozenDict(Mapping[K, V], Generic[K, V]):
    """Small immutable mapping that remains pickle/deepcopy friendly."""

    __slots__ = ("_data",)

    def __init__(
        self,
        values: Mapping[K, V] | Iterable[tuple[K, V]] | None = None,
        **kwargs: V,
    ) -> None:
        data: dict[K, V] = {}
        if values is not None:
            data.update(dict(values))
        if kwargs:
            data.update(kwargs)
        object.__setattr__(self, "_data", MappingProxyType(data))

    def __setattr__(self, name: str, value: Any) -> None:
        raise AttributeError(f"{type(self).__name__} is immutable")

    def __getitem__(self, key: K) -> V:
        return self._data[key]

    def __iter__(self) -> Iterator[K]:
        return iter(self._data)

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self._data!r})"

    def __reduce__(self):
        return (type(self), (dict(self._data),))

    def copy(self) -> dict[K, V]:
        return dict(self._data)


def readonly_array(value: Any, *, dtype: Any | None = None) -> np.ndarray:
    """Return a defensive, read-only numpy array copy for declarative specs."""
    arr = np.array(value, dtype=dtype, copy=True)
    arr.setflags(write=False)
    return arr


def readonly_1d_array(
    value: Any,
    *,
    dtype: Any | None = None,
    error: str = "Array must be one-dimensional",
) -> np.ndarray:
    arr = readonly_array(value, dtype=dtype)
    if arr.ndim != 1:
        raise ValueError(error)
    return arr


def freeze_spec_data(value: Any, *, path: str = "value") -> Any:
    """Freeze and validate language-neutral data carried by canonical specs.

    Extension payloads may contain scalar wire values, NumPy arrays, mappings,
    and sequences. Arbitrary Python objects and callbacks are rejected because
    their class identity cannot be interpreted by non-Python frontends.
    """
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return readonly_array(value)
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise TypeError(f"{path} keys must be non-empty strings")
            frozen[key] = freeze_spec_data(item, path=f"{path}.{key}")
        return FrozenDict(frozen)
    if isinstance(value, (tuple, list)):
        return tuple(
            freeze_spec_data(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        )
    raise TypeError(
        f"{path} must contain only language-neutral spec data; "
        f"got {type(value).__module__}.{type(value).__qualname__}"
    )


__all__ = [
    "FrozenDict",
    "freeze_spec_data",
    "readonly_array",
    "readonly_1d_array",
]
