"""Inline-mode public authoring API.

``source`` wraps the execution source and returns the object that owns
trace/control/action bindings. ``show`` has no arguments; it lowers the declared
source into the same RunSpec/start_app path used by the rest of CompNeuroVis.
"""

from __future__ import annotations

from typing import Any, Callable

from compneurovis.core.messages import CommandPayload
from compneurovis.inline.backend import InlineBackend, SourceStepContext
from compneurovis.inline.sources import (
    ComposedSource,
    InlineSource,
    InlineSourceBase,
    RemoteActorRef,
    RemoteSource,
    _coerce_source,
)


class InlineApp:
    """Internal accumulator for one module-level inline authoring session."""

    def __init__(self) -> None:
        self._sources: list[InlineSourceBase] = []

    def source(self, source_like: Any) -> InlineSourceBase:
        adapter = _coerce_source(source_like)
        self._sources.append(adapter)
        return adapter

    def compose(self, primary: Any, *participants: Any) -> ComposedSource:
        primary_adapter = _coerce_source(primary)
        participant_refs = tuple(
            participant if isinstance(participant, RemoteActorRef) else _coerce_source(participant)
            for participant in participants
        )
        wrapped = {
            id(primary_adapter),
            *(id(participant) for participant in participant_refs if isinstance(participant, InlineSourceBase)),
        }
        self._sources = [source for source in self._sources if id(source) not in wrapped]
        adapter = ComposedSource(
            primary_adapter,
            participants=participant_refs,
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


def _reset_inline_session() -> None:
    global _app
    _app = InlineApp()


_app = InlineApp()


def source(source_like: Any) -> InlineSourceBase:
    return _app.source(source_like)


def compose(primary: Any, *participants: Any) -> ComposedSource:
    return _app.compose(primary, *participants)


def remote(actor_ref: RemoteActorRef) -> RemoteSource:
    return _app.remote(actor_ref)


def remote_actor(
    actor_id: str,
    *,
    send: Callable[[CommandPayload], None] | None = None,
) -> RemoteActorRef:
    return RemoteActorRef(actor_id, send=send)


def show():
    return _app.show()


__all__ = [
    "ComposedSource",
    "InlineApp",
    "InlineBackend",
    "InlineSource",
    "InlineSourceBase",
    "RemoteActorRef",
    "RemoteSource",
    "SourceStepContext",
    "compose",
    "remote",
    "remote_actor",
    "show",
    "source",
]
