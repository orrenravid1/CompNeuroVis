"""Composed and remote source variants."""

from __future__ import annotations

from typing import Any, Callable

from compneurovis.backends.base import BackendBase
from compneurovis.core.app_spec import AppSpec
from compneurovis.core.messages import Invoke, MessagePayload, Reset

from .api import InlineSourceBase


class RemoteActorRef:
    """Reference to an actor hosted outside the current Python source."""

    def __init__(
        self,
        actor_id: str,
        *,
        send: Callable[[MessagePayload], None] | None = None,
    ) -> None:
        self.actor_id = str(actor_id)
        self._send = send

    def command(self, command: MessagePayload) -> None:
        if self._send is None:
            raise RuntimeError(
                "RemoteActorRef without a send callback requires multi-actor RunSpec "
                "routing, which is not wired yet."
            )
        self._send(command)

    def invoke(
        self, interaction_id: str, payload: dict[str, Any] | None = None
    ) -> None:
        self.command(Invoke(interaction_id, payload))

    def reset(self) -> None:
        self.command(Reset())


class ComposedSource(InlineSourceBase):
    """Neutral authoring-layer composition of source declarations."""

    def __init__(
        self,
        sources: tuple[Any, ...],
        *,
        title: str | None = None,
    ) -> None:
        if len(sources) < 2:
            raise ValueError("ComposedSource requires at least two sources")
        super().__init__(title=title or "CompNeuroVis")
        self.sources = tuple(sources)

    def _make_backend(self) -> BackendBase:
        raise NotImplementedError(
            "ComposedSource does not lower to a single backend wrapper. "
            "Composition must compile to explicit multi-actor RunSpec wiring."
        )

    def _compose_app_spec_for_backend(self, backend: BackendBase) -> AppSpec:
        del backend
        raise NotImplementedError(
            "ComposedSource AppSpec compilation needs a multi-source runtime compiler. "
            "No source is privileged to provide the composed AppSpec."
        )


class RemoteSource(InlineSourceBase):
    """Source adapter for an actor hosted outside the current Python process."""

    def __init__(
        self, actor_ref: RemoteActorRef, *, title: str = "CompNeuroVis"
    ) -> None:
        super().__init__(title=title)
        self._actor_ref = actor_ref

    def _make_backend(self) -> BackendBase:
        raise NotImplementedError(
            "RemoteSource does not create a local backend. "
            "Remote source compilation to RunSpec is not yet implemented."
        )

    def _compose_app_spec_for_backend(self, backend: BackendBase) -> AppSpec:
        del backend
        raise NotImplementedError("RemoteSource AppSpec comes from the remote actor.")


__all__ = ["ComposedSource", "RemoteActorRef", "RemoteSource"]
