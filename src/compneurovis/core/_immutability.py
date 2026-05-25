from __future__ import annotations

from typing import Any

import numpy as np


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


__all__ = ["readonly_array", "readonly_1d_array"]
