"""Inline source factory for Jaxley backends."""

from __future__ import annotations

from typing import Any, Callable, Iterable, Sequence

from compneurovis.backends import HistoryCaptureMode
from compneurovis.backends.jaxley.backend import JaxleyBackend
from compneurovis.backends.jaxley.inline import JaxleyInlineSource
from compneurovis.inline.backend import SourceBackendMixin
from compneurovis.inline.data_producers import SeriesProducer
from compneurovis.inline.interactions import ActionInteraction, ControlInteraction


class _SourceBackend(SourceBackendMixin, JaxleyBackend):
    def __init__(
        self,
        *,
        cells: list,
        setup_fn: Callable[[Any, list[Any]], None] | None,
        controls: list[ControlInteraction],
        actions: list[ActionInteraction],
        series: list[SeriesProducer],
        dt: float,
        v_init: float,
        title: str,
        **kwargs,
    ) -> None:
        super().__init__(dt=dt, v_init=v_init, title=title, **kwargs)
        self._provided_cells = cells
        self._setup_fn = setup_fn
        self._init_source_bindings(controls=controls, actions=actions, series=series)

    def build_cells(self) -> Iterable:
        return self._provided_cells

    def setup_model(self, network, cells):
        if self._setup_fn is not None:
            self._setup_fn(network, cells)

    def _emit_batch(self, times_array, steps: list[Any]) -> None:
        super()._emit_batch(times_array, steps)
        self._emit_source_series_updates(auto_sample=False)


class JaxleySource(JaxleyInlineSource):
    """Jaxley source returned by `cnv.jaxley.source()`.

    Construct through the factory so runtime options are validated and passed
    to the optimized Jaxley backend path.
    """

    def __init__(
        self,
        *,
        cells: list,
        setup: Callable[[Any, list[Any]], None] | None,
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
            controls=self._control_bindings,
            actions=self._actions,
            series=self._series,
            selected=self._selected_entity_ids,
            select_multiple=self._select_multiple,
            dt=self._dt,
            v_init=self._v_init,
            title=self._app_title or self.title,
            **self._backend_kwargs,
        )


def source(
    *,
    cells: Sequence,
    setup: Callable[[Any, list[Any]], None] | None = None,
    dt: float = 0.025,
    display_dt: float | None = 0.1,
    flush_dt: float | None = None,
    v_init: float = -70.0,
    max_samples: int = 1000,
    history_capture_mode: HistoryCaptureMode | str = HistoryCaptureMode.ON_DEMAND,
    history_enabled: bool = False,
    title: str = "CompNeuroVis",
) -> JaxleySource:
    """Create a CompNeuroVis Jaxley source for an existing model.

    Args:
        cells: Existing Jaxley cells owned by the model.
        setup: Optional callback invoked as `setup(network, cells)` before
            integration starts.
        dt: Integration step in milliseconds.
        display_dt: Simulation-time interval between display samples.
        flush_dt: Simulation-time interval between frontend update batches.
            `None` or zero flushes every sampled tick.
        v_init: Initialization voltage in millivolts.
        max_samples: Maximum retained selected-segment history samples.
        history_capture_mode: `"on_demand"` to retain selected histories
            or `"full"` to retain all displayed segment histories.
        history_enabled: Enable history collection before a history-consuming
            view is declared.
        title: Fallback window title. `cnv.show(title=...)` overrides it.

    Returns:
        A bare Jaxley source. Views remain opt-in.
    """

    return JaxleySource(
        cells=list(cells),
        setup=setup,
        dt=dt,
        v_init=v_init,
        backend_kwargs={
            "display_dt": display_dt,
            "flush_dt": flush_dt,
            "max_samples": max_samples,
            "history_capture_mode": history_capture_mode,
            "history_enabled": history_enabled,
        },
        title=title,
    )


__all__ = ["JaxleySource", "source"]
