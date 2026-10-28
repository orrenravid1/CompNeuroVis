"""Mutable composition state for one inline-authored application."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Callable

from compneurovis.backends.interaction import BackendInteractionContext
from compneurovis.inline.sources import (
    ComposedSource,
    InlineSource,
    InlineSourceBase,
    RemoteActorRef,
    RemoteSource,
)


class InlineApp:
    """Accumulate sources and layout before lowering and launch."""

    def __init__(self) -> None:
        self._sources: list[InlineSourceBase] = []
        self._panel_grid: tuple[tuple[str, ...], ...] | None = None

    def register(self, source: InlineSourceBase) -> None:
        if all(source is not existing for existing in self._sources):
            self._sources.append(source)

    def unregister(self, source: InlineSourceBase) -> None:
        """Remove one directly launched source from this declaration session."""
        self._sources = [
            existing for existing in self._sources if existing is not source
        ]
        if not self._sources:
            self._panel_grid = None

    def layout(self, rows: Any) -> None:
        """Arrange the app's panels into a grid of rows."""
        self._panel_grid = tuple(
            tuple(item.id if hasattr(item, "id") else str(item) for item in row)
            for row in rows
        )

    def source(
        self,
        source_like: InlineSourceBase
        | Callable[[BackendInteractionContext], None]
        | Iterable[Any]
        | None = None,
    ) -> InlineSourceBase:
        adapter = source_from_authoring_value(source_like)
        self.register(adapter)
        return adapter

    def compose(self, *sources: Any) -> ComposedSource:
        if len(sources) < 2:
            raise ValueError("cnv.compose(...) requires at least two sources")
        source_refs = tuple(
            source
            if isinstance(source, RemoteActorRef)
            else source_from_authoring_value(source)
            for source in sources
        )
        wrapped = {
            id(source)
            for source in source_refs
            if isinstance(source, InlineSourceBase)
        }
        self._sources = [
            source for source in self._sources if id(source) not in wrapped
        ]
        composed = ComposedSource(source_refs)
        self.register(composed)
        return composed

    def remote(self, actor_ref: RemoteActorRef) -> RemoteSource:
        source = RemoteSource(actor_ref)
        self.register(source)
        return source

    def show(self, *, title: str | None = None):
        if not self._sources:
            raise RuntimeError(
                "cnv.show() found no source. Create one first "
                "(e.g. cnv.source() or cnv.neuron.source(...))."
            )
        if title is not None:
            for source in self._sources:
                source._app_title = title
        if len(self._sources) > 1:
            if self._panel_grid is not None:
                raise NotImplementedError(
                    "cnv.layout(...) across multiple composed sources is not wired "
                    "yet; the integrated app-spec compiler must place the grid. "
                    "Lay out a single source for now."
                )
            from compneurovis._source_runtime import launch_sources

            return launch_sources(tuple(self._sources))
        if self._panel_grid is not None:
            self._sources[0]._panel_grid = self._panel_grid
        return self._sources[0].launch()


def source_from_authoring_value(value: Any = None) -> InlineSourceBase:
    """Adapt a source-level input without mutating the current authoring app."""
    if isinstance(value, InlineSourceBase):
        return value
    if value is None:
        return InlineSource(None)
    if callable(value):
        return InlineSource(value)
    try:
        return InlineSource(iter(value))
    except TypeError as exc:
        raise TypeError(
            "cnv.source(...) expects no argument, a source, callable, or iterator."
        ) from exc


__all__ = ["InlineApp", "source_from_authoring_value"]
