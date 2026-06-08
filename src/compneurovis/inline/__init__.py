"""Inline-mode public authoring API.

``source`` wraps the execution source and returns the object that owns
trace/control/action bindings. ``show`` has no arguments; it lowers the declared
source into the same RunSpec/start_app path used by the rest of CompNeuroVis.
"""

from __future__ import annotations

from typing import Any, Callable

from compneurovis.core.messages import CommandPayload
from compneurovis.inline.backend import InlineBackend, TraceSampler
from compneurovis.inline.sources import (
    ComposedSource,
    InlineSource,
    InlineSourceBase,
    RemoteActorRef,
    RemoteSource,
)


class InlineApp:
    """Internal accumulator for one module-level inline authoring session."""

    def __init__(self) -> None:
        self._sources: list[InlineSourceBase] = []

    def source(self, source_like: Any, *, trace_sampler: bool = False) -> InlineSourceBase:
        adapter = _source_from_authoring_value(source_like, trace_sampler=trace_sampler)
        self._sources.append(adapter)
        return adapter

    def compose(self, *sources: Any) -> ComposedSource:
        if len(sources) < 2:
            raise ValueError("cnv.compose(...) requires at least two sources")
        source_refs = tuple(
            source if isinstance(source, RemoteActorRef) else _source_from_authoring_value(source)
            for source in sources
        )
        wrapped = {
            id(source)
            for source in source_refs
            if isinstance(source, InlineSourceBase)
        }
        self._sources = [source for source in self._sources if id(source) not in wrapped]
        adapter = ComposedSource(
            source_refs,
        )
        self._sources.append(adapter)
        return adapter

    def remote(self, actor_ref: RemoteActorRef) -> RemoteSource:
        adapter = RemoteSource(actor_ref)
        self._sources.append(adapter)
        return adapter

    def show(self):
        if not self._sources:
            raise RuntimeError("cnv.show() requires at least one cnv.source(...) call.")
        if len(self._sources) > 1:
            raise NotImplementedError(
                "Multiple cnv.source(...) calls are accepted by the authoring API, "
                "but multi-backend routing is not implemented yet."
            )
        return self._sources[0].launch()


def _source_from_authoring_value(value: Any, *, trace_sampler: bool = False) -> InlineSourceBase:
    if isinstance(value, InlineSourceBase):
        if trace_sampler:
            raise TypeError("trace_sampler=True only applies to callable sources.")
        return value
    if callable(value):
        return InlineSource(value, trace_sampler=trace_sampler)
    if trace_sampler:
        raise TypeError("trace_sampler=True only applies to callable sources.")
    try:
        return InlineSource(iter(value))
    except TypeError as exc:
        raise TypeError("cnv.source(...) expects a source, callable, or iterator.") from exc


def _reset_inline_session() -> None:
    global _app
    _app = InlineApp()


_app = InlineApp()


def source(source_like: Any, *, trace_sampler: bool = False) -> InlineSourceBase:
    return _app.source(source_like, trace_sampler=trace_sampler)


def compose(*sources: Any) -> ComposedSource:
    return _app.compose(*sources)


def remote(actor_ref: RemoteActorRef) -> RemoteSource:
    return _app.remote(actor_ref)


def remote_actor(
    actor_id: str,
    *,
    send: Callable[[CommandPayload], None] | None = None,
) -> RemoteActorRef:
    return RemoteActorRef(actor_id, send=send)


def show(build: Callable[[], Any] | None = None):
    """Show the inline UI.

    ``cnv.show()`` runs the source in-kernel (light sims). ``cnv.show(build)``
    runs the sim in a child process built from ``build`` and renders in the
    kernel — so a heavy sim cannot starve the render. ``build`` must construct
    the model from scratch and return the configured source, capturing no live
    model objects (it is shipped to the child via cloudpickle).
    """
    if build is not None:
        from compneurovis._source_runtime import launch_notebook_source_process

        return launch_notebook_source_process(build)
    return _app.show()


__all__ = [
    "ComposedSource",
    "InlineApp",
    "InlineBackend",
    "InlineSource",
    "InlineSourceBase",
    "RemoteActorRef",
    "RemoteSource",
    "TraceSampler",
    "compose",
    "remote",
    "remote_actor",
    "show",
    "source",
]
