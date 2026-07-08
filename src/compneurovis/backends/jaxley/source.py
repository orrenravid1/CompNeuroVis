"""Inline source factory for Jaxley backends."""

from __future__ import annotations

from typing import Any, Callable, Iterable, Sequence

from compneurovis.backends.jaxley.backend import JaxleyBackend
from compneurovis.backends.jaxley.inline import JaxleyInlineSource
from compneurovis.core.controls import ActionSpec, ControlSpec
from compneurovis.inline.bindings import ActionBinding, ControlBinding, TraceBinding, TraceSampler, emit_trace_updates


class _SourceBackend(JaxleyBackend):
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
        self._provided_controls = controls
        self._provided_actions = actions
        self._provided_traces = traces
        self._trace_sampler = TraceSampler(traces)

    def build_cells(self) -> Iterable:
        return self._provided_cells

    def setup_model(self, network, cells):
        if self._setup_fn is not None:
            self._setup_fn(network, cells)

    def control_specs(self) -> dict[str, ControlSpec]:
        return {control._control_id: control._control_spec() for control in self._provided_controls}

    def control_values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for control in self._provided_controls:
            get = getattr(control, "get", None)
            if get is not None:
                values[control._control_id] = get()
            else:
                spec = control._control_spec()
                values[control._control_id] = self._ui_state.get(spec.resolved_state_key(), spec.default_value())
        return values

    def action_specs(self) -> dict[str, ActionSpec]:
        return {action._action_id: action._action_spec() for action in self._provided_actions}

    def apply_control(self, control_id: str, value: Any) -> bool:
        for control in self._provided_controls:
            if control._control_id == control_id:
                if not control.apply(self, value):
                    return False
                self._ui_state[control_id] = value
                return True
        return False

    def on_action(self, action_id: str, payload: dict, context: Any) -> bool:
        del payload
        for action in self._provided_actions:
            if action._action_id == action_id:
                action.fn(context)
                if action.resets_fields:
                    for trace in self._provided_traces:
                        self.emit_update(trace._replace_message().payload)
                return True
        return False

    def idle_sleep(self) -> float:
        return 1.0 / 60.0

    def _emit_batch(self, times_array, steps: list[Any]) -> None:
        super()._emit_batch(times_array, steps)
        for trace in self._provided_traces:
            trace._begin_frame()
            trace._sample()
        emit_trace_updates(self, self._provided_traces, auto_sample=False)


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