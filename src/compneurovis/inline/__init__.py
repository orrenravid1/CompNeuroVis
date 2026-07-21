"""Inline-mode public authoring API.

Sources declare app fragments; ``show`` integrates them into one visible app.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any, Callable

from compneurovis.backends.interaction import BackendInteractionContext
from compneurovis.core.messages import CommandPayload
from compneurovis.inline.backend import InlineBackend
from compneurovis.inline.handles import PanelHandle
from compneurovis.inline.sampling import TraceSampler
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
        self._panel_grid: tuple[tuple[str, ...], ...] | None = None

    def register(self, source: InlineSourceBase) -> None:
        if all(source is not existing for existing in self._sources):
            self._sources.append(source)

    def layout(self, rows: Any) -> None:
        """Arrange the app's panels into a grid of rows.

        App-level, like matplotlib's ``subplot_mosaic``: takes the panel handles
        returned by ``src.morphology()`` / ``src.line()`` / ``src.surface()`` (or
        panel-id strings such as ``"controls-panel"``) and lays them out. Layout
        belongs to the app/figure, not to any one source -- so it lives here, not
        on ``src``, and ``cnv.show()`` stays a pure render trigger.
        """
        self._panel_grid = tuple(
            tuple(item.id if hasattr(item, "id") else str(item) for item in row)
            for row in rows
        )

    def source(self, source_like: Any = None) -> InlineSourceBase:
        adapter = _source_from_authoring_value(source_like)
        self.register(adapter)
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
        return ComposedSource(source_refs)

    def remote(self, actor_ref: RemoteActorRef) -> RemoteSource:
        return RemoteSource(actor_ref)

    def show(self, *, title: str | None = None):
        if not self._sources:
            raise RuntimeError(
                "cnv.show() found no source. Create one first (e.g. cnv.source() or cnv.neuron.source(...))."
            )
        if title is not None:
            for source in self._sources:
                source._app_title = title
        if len(self._sources) > 1:
            if self._panel_grid is not None:
                raise NotImplementedError(
                    "cnv.layout(...) across multiple composed sources is not wired yet; "
                    "the integrated app-spec compiler must place the grid. Lay out a "
                    "single source for now."
                )
            from compneurovis._source_runtime import launch_sources

            return launch_sources(tuple(self._sources))
        if self._panel_grid is not None:
            self._sources[0]._panel_grid = self._panel_grid
        return self._sources[0].launch()


def _source_from_authoring_value(value: Any = None) -> InlineSourceBase:
    if isinstance(value, InlineSourceBase):
        return value
    if value is None:
        return InlineSource(None)
    if callable(value):
        return InlineSource(value)
    try:
        return InlineSource(iter(value))
    except TypeError as exc:
        raise TypeError("cnv.source(...) expects no argument, a source, callable, or iterator.") from exc


def _reset_inline_session() -> None:
    global _app
    _app = InlineApp()


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

    Args:
        source_like: Optional source behavior. Pass a callable invoked as
            `source_like(ctx)` once per update, an iterator advanced once per
            update, an existing source, or `None` for a static UI.

    Returns:
        A source on which views, controls, values, and actions can be declared.

    Simulator models should use `cnv.neuron.source()` or
    `cnv.jaxley.source()` so their native sampling paths remain available.
    """
    return _app.source(source_like)


def compose(*sources: Any) -> ComposedSource:
    return _app.compose(*sources)


def layout(rows: Sequence[Sequence[PanelHandle | str]]) -> None:
    """Arrange app panels into a grid, similar to `subplot_mosaic`.

    Args:
        rows: Sequence of rows containing panel handles returned by source view
            methods. Advanced callers may also use panel-id strings.

    Layout belongs to the integrated app rather than an individual source.
    Call this after declaring panels and before `cnv.show()`.
    """
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
    """Integrate declared sources and show one app.

    Args:
        build: Optional no-argument source builder for the notebook child-process
            path. Normal scripts should declare sources directly and omit this.
        title: Optional app-window title.

    Returns:
        The launched app handle or notebook process handle.
    """
    if build is not None:
        from compneurovis._source_runtime import launch_notebook_source_process

        return launch_notebook_source_process(build)
    return _app.show(title=title)


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
    "layout",
    "remote",
    "remote_actor",
    "show",
    "source",
]
