from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import fields, is_dataclass, replace
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


class FrozenList(list[V], Generic[V]):
    """List-compatible immutable sequence for snapshotted runtime values."""

    __slots__ = ()

    @staticmethod
    def _immutable(*_args: Any, **_kwargs: Any) -> None:
        raise TypeError("FrozenList is immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable

    def __reduce__(self):
        return (type(self), (list(self),))


def readonly_array(value: Any, *, dtype: Any | None = None) -> np.ndarray:
    """Return a defensive, read-only numpy array copy for declarative specs."""
    arr = np.array(value, dtype=dtype, copy=True)
    if arr.dtype.hasobject:
        raise TypeError(
            "Object-dtype arrays are not safe canonical values; use a numeric, "
            "boolean, or string dtype"
        )
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
        return freeze_spec_data(value.item(), path=path)
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


def snapshot_message_data(value: Any, *, path: str = "value") -> Any:
    """Take an immutable snapshot of data crossing an actor boundary.

    Message payloads may contain canonical specs in addition to ordinary wire
    values. Specs are already immutable; containers and arrays surrounding
    them still need defensive copies so in-process and serialized transports
    observe the same value even if the sender later mutates its inputs.
    """

    return _snapshot_message_data(value, path=path, memo={})


_NOT_MEMOIZED = object()
_SNAPSHOT_IN_PROGRESS = object()


def _snapshot_message_data(
    value: Any,
    *,
    path: str,
    memo: dict[int, Any],
) -> Any:
    from compneurovis.core.specs import SpecBase

    if value is None or isinstance(value, (str, bytes, bool, int, float)):
        return value
    if isinstance(value, np.generic):
        return _snapshot_message_data(value.item(), path=path, memo=memo)

    identity = id(value)
    existing = memo.get(identity, _NOT_MEMOIZED)
    if existing is _SNAPSHOT_IN_PROGRESS:
        raise TypeError(f"{path} cannot contain recursive containers or specs")
    if existing is not _NOT_MEMOIZED:
        return existing

    if isinstance(value, SpecBase):
        params = getattr(type(value), "__dataclass_params__", None)
        if not is_dataclass(value) or params is None or not params.frozen:
            raise TypeError(
                f"{path} spec values must be frozen dataclasses; "
                f"got {type(value).__module__}.{type(value).__qualname__}"
            )
        memo[identity] = _SNAPSHOT_IN_PROGRESS
        updates = {
            item.name: _snapshot_message_data(
                getattr(value, item.name),
                path=f"{path}.{item.name}",
                memo=memo,
            )
            for item in fields(value)
            if item.init
        }
        result = replace(value, **updates)
        memo[identity] = result
        return result
    if isinstance(value, np.ndarray):
        result = readonly_array(value)
        memo[identity] = result
        return result
    if isinstance(value, Mapping):
        memo[identity] = _SNAPSHOT_IN_PROGRESS
        frozen: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.strip():
                raise TypeError(f"{path} keys must be non-empty strings")
            frozen[key] = _snapshot_message_data(
                item,
                path=f"{path}.{key}",
                memo=memo,
            )
        result = FrozenDict(frozen)
        memo[identity] = result
        return result
    if isinstance(value, tuple):
        memo[identity] = _SNAPSHOT_IN_PROGRESS
        result = tuple(
            _snapshot_message_data(
                item,
                path=f"{path}[{index}]",
                memo=memo,
            )
            for index, item in enumerate(value)
        )
        memo[identity] = result
        return result
    if isinstance(value, list):
        memo[identity] = _SNAPSHOT_IN_PROGRESS
        result = FrozenList(
            _snapshot_message_data(
                item,
                path=f"{path}[{index}]",
                memo=memo,
            )
            for index, item in enumerate(value)
        )
        memo[identity] = result
        return result
    raise TypeError(
        f"{path} must contain message-safe data or immutable specs; "
        f"got {type(value).__module__}.{type(value).__qualname__}"
    )


__all__ = [
    "FrozenDict",
    "FrozenList",
    "freeze_spec_data",
    "readonly_array",
    "readonly_1d_array",
    "snapshot_message_data",
]
