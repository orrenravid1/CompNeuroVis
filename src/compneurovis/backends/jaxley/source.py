"""Inline source factory for Jaxley backends."""

from __future__ import annotations

from typing import Any, Callable, Iterable, Sequence

from compneurovis.backends.jaxley.backend import JaxleyBackend
from compneurovis.backends.jaxley.inline import JaxleyInlineSource
from compneurovis.inline.backend import SourceBackendMixin
from compneurovis.inline.bindings import ActionBinding, ControlBinding, TraceBinding


class _SourceBackend(SourceBackendMixin, JaxleyBackend):
    def __init__(
        self,
        *,
        cells: list,
        setup_fn: Callable | None,
        controls: list[ControlBinding],
        actions: list[ActionBinding],
        traces: list[TraceBinding],
        dt: float,
        v_init: float,
        title: str,
        **kwargs,
    ) -> None:
        super().__init__(dt=dt, v_init=v_init, title=title, display_dt=kwargs.pop("display_dt", 50.0), **kwargs)
        self._provided_cells = cells
        self._setup_fn = setup_fn
        self._init_source_bindings(controls=controls, actions=actions, traces=traces)

    def build_cells(self) -> Iterable:
        return self._provided_cells

    def setup_model(self, network, cells):
        if self._setup_fn is not None:
            self._setup_fn(network, cells)

    def _emit_batch(self, times_array, steps: list[Any]) -> None:
        super()._emit_batch(times_array, steps)
        self._emit_source_trace_updates(auto_sample=False)


class JaxleySource(JaxleyInlineSource):
    def __init__(
        self,
        *,
        cells: list,
        setup: Callable | None,
        dt: float,
        v_init: float,
        backend_kwargs: dict,
        title: str = "CompNeuroVis",
    ) -> None:
        super().__init__(title=title)
        self._cells = cells
        self._setup_fn = setup
        self._dt = dt
        self._v_init = v_init
        self._backend_kwargs = backend_kwargs

    def _make_backend(self) -> _SourceBackend:
        return _SourceBackend(
            cells=self._cells,
            setup_fn=self._setup_fn,
            controls=self._controls,
            actions=self._actions,
            traces=self._traces,
            dt=self._dt,
            v_init=self._v_init,
            title=self._app_title or self.title,
            **self._backend_kwargs,
        )


def source(
    *,
    cells: Sequence,
    setup: Callable | None = None,
    dt: float = 0.025,
    v_init: float = -70.0,
    title: str = "CompNeuroVis",
    **kwargs,
) -> JaxleySource:
    """Create a CompNeuroVis Jaxley source for an existing model."""

    return JaxleySource(
        cells=list(cells),
        setup=setup,
        dt=dt,
        v_init=v_init,
        backend_kwargs=kwargs,
        title=title,
    )


__all__ = ["JaxleySource", "source"]