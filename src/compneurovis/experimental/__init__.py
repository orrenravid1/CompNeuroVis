"""Incomplete authoring paths excluded from the supported alpha API."""

from compneurovis.inline import compose, remote, remote_actor
from compneurovis.inline.sources import ComposedSource, RemoteActorRef, RemoteSource

__all__ = [
    "ComposedSource",
    "RemoteActorRef",
    "RemoteSource",
    "compose",
    "remote",
    "remote_actor",
]
