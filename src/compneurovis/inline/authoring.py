"""Module-level public façade for inline application authoring."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Callable

from compneurovis.backends.interaction import BackendInteractionContext
from compneurovis.core.messages import CommandPayload
from compneurovis.inline.app import InlineApp
from compneurovis.inline.refs import PanelRef
from compneurovis.inline.sources import (
    ComposedSource,
    InlineSourceBase,
    RemoteActorRef,
    RemoteSource,
)


_app = InlineApp()


def _current_authoring_app() -> InlineApp:
    """Return the current accumulator for tests and launch plumbing."""
    return _app


def _reset_authoring_app() -> None:
    global _app
    _app = InlineApp()


def _register_current_source(source: InlineSourceBase) -> None:
    _app.register(source)


def source(
    source_like: InlineSourceBase
    | Callable[[BackendInteractionContext], None]
    | Iterable[Any]
    | None = None,
) -> InlineSourceBase:
    """Create a generic inline source.

    Simulator models should use `cnv.neuron.source()` or
    `cnv.jaxley.source()` so their native sampling paths remain available.
    """
    return _app.source(source_like)


def compose(*sources: Any) -> ComposedSource:
    return _app.compose(*sources)


def layout(rows: Sequence[Sequence[PanelRef | str]]) -> None:
    """Arrange app panels into a grid owned by the integrated app."""
    _app.layout(rows)


def remote(actor_ref: RemoteActorRef) -> RemoteSource:
    return _app.remote(actor_ref)


def remote_actor(
    actor_id: str,
    *,
    send: Callable[[CommandPayload], None] | None = None,
) -> RemoteActorRef:
    return RemoteActorRef(actor_id, send=send)


def show(build: Callable[[], Any] | None = None, *, title: str | None = None):
    """Integrate declared sources and show one app."""
    if build is not None:
        from compneurovis._source_runtime import launch_notebook_source_process

        return launch_notebook_source_process(build)
    return _app.show(title=title)


__all__ = [
    "compose",
    "layout",
    "remote",
    "remote_actor",
    "show",
    "source",
]
