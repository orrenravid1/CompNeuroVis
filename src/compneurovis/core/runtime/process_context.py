from __future__ import annotations

import multiprocessing as mp
from multiprocessing.context import BaseContext


def spawn_context() -> BaseContext:
    """Return the spawn context without changing the process default."""

    return mp.get_context("spawn")


def prepare_multiprocessing() -> None:
    """Perform frozen-executable setup without replacing embedding policy."""

    mp.freeze_support()


__all__ = ["prepare_multiprocessing", "spawn_context"]
