"""Shared inline-authoring composition layer for NEURON attach sources.

``NeuronAttachSource`` wraps raw sections and declares views and panels over the
fields their backend emits. That vocabulary -- ``morphology``, ``history``,
``line``, ``state_graph``, ``controls``, ``layout`` -- is backend-agnostic and
lives here once so AppSpec composition stays separate from attach-specific
runtime sampling.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from compneurovis.backends.base import BackendBase
from compneurovis.backends.neuron.app_spec import NeuronAppSpecBuilder
from compneurovis.backends.neuron.backend import NeuronBackend
from compneurovis.core.app_spec import (
    AppSpec,
    DataCatalog,
    InteractionCatalog,
    LayoutCatalog,
    LayoutSpec,
    PANEL_KIND_CONTROLS,
    PANEL_KIND_LINE_PLOT,
    PANEL_KIND_STATE_GRAPH,
    PANEL_KIND_VIEW_3D,
    PanelSpec,
    ViewCatalog,
)
from compneurovis.core.controls import (
    ActionSpec,
    ControlPresentationSpec,
    ControlSpec,
    ControlValueSpec,
    ScalarValueSpec,
)
from compneurovis.core.field import FieldSpec
from compneurovis.core.state import StateBindingSpec
from compneurovis.core.views import LinePlotViewSpec, MorphologyViewSpec, StateGraphViewSpec
from compneurovis.inline.bindings import (
    ActionBinding,
    ActionHandle,
    ControlBinding,
    ControlHandle,
    append_bindings_to_app_spec,
)
from compneurovis.inline.sources import InlineSourceBase

# Callable arities accepted by interaction-hook functions. Hooks are invoked
# with as many positional args as they declare, so authors can write
# ``fn()``, ``fn(ctx)``, or ``fn(ctx, payload)`` and get only what they ask for.
ClickHandler = Callable[..., Any]
KeyHandler = Callable[..., Any]
SampleFn = Callable[[], Any]


@dataclass(frozen=True, slots=True)
class PanelHandle:
    """User-facing reference to a panel, usable in ``layout(...)`` rows."""

    id: str


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(value).strip()).strip("_").lower() or "item"


def _time_coord(backend: NeuronBackend) -> np.ndarray:
    value = getattr(backend, "_last_time_value", None)
    return np.asarray([0.0 if value is None else float(value)], dtype=np.float32)


def _coerce_series_initial(values: Any, series_count: int) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float32)
    if arr.ndim == 0:
        arr = arr.reshape(1, 1)
    elif arr.ndim == 1:
        arr = arr.reshape(arr.shape[0], 1)
    if arr.shape[0] != series_count:
        raise ValueError(f"Initial line values have {arr.shape[0]} series, expected {series_count}")
    return arr


def _positional_arg_count(fn: Callable[..., Any]) -> int:
    """Number of positional params a callable accepts (``inf`` for ``*args``)."""
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return 1
    params = tuple(signature.parameters.values())
    if any(param.kind == inspect.Parameter.VAR_POSITIONAL for param in params):
        return 1_000_000
    return sum(
        1 for param in params
        if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    )


def _callable_accepts_backend_arg(fn: Callable[..., Any]) -> bool:
    return _positional_arg_count(fn) >= 2


def _call_with_args(fn: Callable[..., Any], *args: Any) -> Any:
    """Invoke ``fn`` with at most as many leading positional args as it declares."""
    return fn(*args[: _positional_arg_count(fn)])


@dataclass
class NeuronControlBinding(ControlBinding):
    """Inline control with an arbitrary value spec/presentation.

    A scalar slider falls out of ``get``/``min``/``max`` when no ``value_spec`` is
    given; pass ``value_spec``/``presentation`` for xy-pads, dropdowns, log
    sliders, etc. ``set`` receives the raw value (a number, or a dict for xy) and
    may optionally take the backend as a leading arg.
    """

    value_spec: ControlValueSpec | None = None
    presentation: ControlPresentationSpec | None = None

    def _control_spec(self) -> ControlSpec:
        if self.value_spec is not None:
            value_spec: ControlValueSpec = self.value_spec
        else:
            default = self.get() if self.get is not None else 0.0
            value_spec = ScalarValueSpec(default=default, min=self.min, max=self.max)
        return ControlSpec(
            id=self._control_id,
            label=self.label,
            value_spec=value_spec,
            presentation=self.presentation,
            send_to_backend=True,
        )

    def apply(self, backend: NeuronBackend, value: Any) -> bool:
        _call_with_args(self.set, backend, value) if _callable_accepts_backend_arg(self.set) else self.set(value)
        return True


@dataclass
class NeuronActionBinding(ActionBinding):
    """Inline action whose handler may accept ``(ctx)`` or ``(ctx, payload)``.

    Carries shortcut keys so the action can also fire from the keyboard, and is
    dispatched with an interaction context -- resolving the zero-arg-action gap
    so actions can show status, set selection state, or invoke other actions.
    """

    shortcuts: tuple[str, ...] = ()

    def _action_spec(self) -> ActionSpec:
        return ActionSpec(id=self._action_id, label=self.label, shortcuts=tuple(self.shortcuts))

    def invoke(self, context: Any, payload: dict[str, Any]) -> None:
        _call_with_args(self.fn, context, payload)


@dataclass
class LineRecorder:
    """Per-tick sampler feeding a declared ``line(...)`` field.

    The attach backend calls ``sample()`` once per integration step, stacks the
    batch, and appends it to ``field_id`` along ``series_dim``/time. ``sample``
    returns one value per series (array-like of length ``len(series)``).
    """

    field_id: str
    series_dim: str
    series: tuple[str, ...]
    sample: SampleFn
    max_samples: int = 5000

    def sample_vector(self) -> np.ndarray:
        return np.asarray(self.sample(), dtype=np.float32).reshape(len(self.series))


class NeuronInlineSource(InlineSourceBase):
    """Shared composition vocabulary for NEURON inline attach sources.

    Subclasses provide ``_make_backend``; everything below -- view/panel
    declaration and AppSpec assembly -- is shared by attach-owned source
    variants.
    """

    def __init__(self, *, title: str = "CompNeuroVis") -> None:
        super().__init__(title=title)
        self._fields: list[Callable[[NeuronBackend], FieldSpec]] = []
        self._views: list[Any] = []
        self._panels: list[PanelSpec] = []
        self._panel_grid: tuple[tuple[str, ...], ...] | None = None
        self._extra_controls: dict[str, ControlSpec] = {}
        self._include_controls = False
        self._controls_panel_id = "controls-panel"
        self._control_ids: tuple[str, ...] | None = None
        self._action_ids: tuple[str, ...] | None = None
        # Runtime hooks, executed by the attach-owned backend.
        self._recorders: list[LineRecorder] = []
        self._click_handlers: list[ClickHandler] = []
        self._key_handlers: list[KeyHandler] = []
        self._capture_predicate: ClickHandler | None = None
        self._initial_state: list[tuple[str, Any]] = []

    # -- authoring vocabulary -------------------------------------------------

    def morphology(
        self,
        name: str = "Morphology",
        *,
        color_field_id: str | None = None,
        color_map: str = "scalar",
        color_limits: tuple[float, float] | None = (-80.0, 50.0),
        color_norm: str = "auto",
        background_color: Any = "white",
        max_refresh_hz: float | None = None,
    ) -> PanelHandle:
        slug = _slug(name)
        view_id = slug
        panel_id = f"{slug}-panel"
        self._views.append(
            lambda backend: MorphologyViewSpec(
                id=view_id,
                title=name,
                geometry_id=backend.geometry.id,
                color_field_id=color_field_id or NeuronAppSpecBuilder.DISPLAY_FIELD_ID,
                entity_dim="segment",
                sample_dim=None,
                color_map=color_map,
                color_limits=color_limits,
                color_norm=color_norm,
                background_color=background_color,
                max_refresh_hz=max_refresh_hz,
            )
        )
        self._panels.append(PanelSpec(id=panel_id, kind=PANEL_KIND_VIEW_3D, view_ids=(view_id,)))
        return PanelHandle(panel_id)

    def history(
        self,
        name: str = "Trace",
        *,
        field_id: str | None = None,
        by: str | None = None,
        select: dict[str, Any] | None = None,
        y_label: str = "Value",
        y_unit: str = "mV",
        rolling_window: float | None = 500.0,
        **style: Any,
    ) -> PanelHandle:
        return self.line(
            name,
            field_id=field_id or NeuronAppSpecBuilder.HISTORY_FIELD_ID,
            x="time",
            by=by,
            select=select if select is not None else {"segment": StateBindingSpec("selected_entity_id")},
            y_label=y_label,
            y_unit=y_unit,
            rolling_window=rolling_window,
            **style,
        )

    def line(
        self,
        name: str,
        *,
        field_id: str | None = None,
        series: Sequence[str] | None = None,
        initial: Callable[[NeuronBackend], Any] | Sequence[float] | np.ndarray | None = None,
        record: SampleFn | None = None,
        max_samples: int = 5000,
        unit: str | None = None,
        x: str | None = "time",
        by: str | None = None,
        select: dict[str, Any] | None = None,
        panel_id: str | None = None,
        **style: Any,
    ) -> PanelHandle:
        slug = _slug(name)
        resolved_field_id = field_id or f"{slug}_field"
        view_id = f"{slug}_plot"
        resolved_panel_id = panel_id or f"{slug}-panel"
        series_dim = by or ("series" if series is not None else None)

        if record is not None and series is None:
            raise ValueError("line(record=...) requires series=[...] to name the recorded channels")

        if series is not None:
            labels = tuple(str(item) for item in series)

            def build_field(backend: NeuronBackend) -> FieldSpec:
                if initial is not None:
                    raw: Any = initial(backend) if callable(initial) else initial
                elif record is not None:
                    raw = record()
                else:
                    raw = None
                values = _coerce_series_initial(
                    np.zeros((len(labels), 1), dtype=np.float32) if raw is None else raw,
                    len(labels),
                )
                return FieldSpec(
                    id=resolved_field_id,
                    initial_values=values,
                    dims=(series_dim or "series", "time"),
                    coords={
                        series_dim or "series": np.asarray(labels),
                        "time": _time_coord(backend),
                    },
                    unit=unit,
                )

            self._fields.append(build_field)
            if record is not None:
                self._recorders.append(
                    LineRecorder(
                        field_id=resolved_field_id,
                        series_dim=series_dim or "series",
                        series=labels,
                        sample=record,
                        max_samples=max_samples,
                    )
                )

        view_kwargs = dict(style)
        title = view_kwargs.pop("title", name)
        view = LinePlotViewSpec(
            id=view_id,
            title=title,
            field_id=resolved_field_id,
            x_dim=x,
            series_dim=series_dim,
            selectors={} if select is None else dict(select),
            **view_kwargs,
        )
        self._views.append(view)
        self._panels.append(PanelSpec(id=resolved_panel_id, kind=PANEL_KIND_LINE_PLOT, view_ids=(view_id,)))
        return PanelHandle(resolved_panel_id)

    def state_graph(
        self,
        name: str,
        *,
        node_field_id: str,
        edge_field_id: str,
        node_positions: tuple[tuple[str, float, float], ...],
        edges: tuple[tuple[str, str, str], ...],
        node_names: Sequence[str] | None = None,
        edge_names: Sequence[str] | None = None,
        panel_id: str | None = None,
        **style: Any,
    ) -> PanelHandle:
        slug = _slug(name)
        view_id = f"{slug}_graph"
        resolved_panel_id = panel_id or f"{slug}-panel"
        node_labels = tuple(node_names or [item[0] for item in node_positions])
        edge_labels = tuple(edge_names or [item[2] for item in edges])
        self._fields.extend(
            (
                lambda backend: FieldSpec(
                    id=node_field_id,
                    initial_values=np.zeros(len(node_labels), dtype=np.float32),
                    dims=("state",),
                    coords={"state": np.asarray(node_labels)},
                ),
                lambda backend: FieldSpec(
                    id=edge_field_id,
                    initial_values=np.zeros(len(edge_labels), dtype=np.float32),
                    dims=("edge",),
                    coords={"edge": np.asarray(edge_labels)},
                ),
            )
        )
        view_kwargs = dict(style)
        title = view_kwargs.pop("title", name)
        self._views.append(
            StateGraphViewSpec(
                id=view_id,
                title=title,
                node_field_id=node_field_id,
                edge_field_id=edge_field_id,
                node_positions=node_positions,
                edges=edges,
                **view_kwargs,
            )
        )
        self._panels.append(PanelSpec(id=resolved_panel_id, kind=PANEL_KIND_STATE_GRAPH, view_ids=(view_id,)))
        return PanelHandle(resolved_panel_id)

    def controls(
        self,
        name: str = "Controls",
        *,
        control_ids: tuple[str, ...] | None = None,
        action_ids: tuple[str, ...] | None = None,
    ) -> PanelHandle:
        self._include_controls = True
        self._controls_panel_id = f"{_slug(name)}-panel"
        self._control_ids = control_ids
        self._action_ids = action_ids
        return PanelHandle(self._controls_panel_id)

    def control(
        self,
        name: str,
        *,
        label: str,
        set: Callable[..., None],
        get: Callable[[], Any] | None = None,
        min: float = 0.0,
        max: float = 1.0,
        value_spec: ControlValueSpec | None = None,
        presentation: ControlPresentationSpec | None = None,
    ) -> ControlHandle:
        binding = NeuronControlBinding(
            name=name,
            label=label,
            get=get,
            set=set,
            min=min,
            max=max,
            value_spec=value_spec,
            presentation=presentation,
        )
        self._add_control(binding)
        return ControlHandle(binding)

    def action(
        self,
        name: str,
        *,
        label: str,
        fn: Callable[..., None],
        resets_fields: bool = False,
        shortcuts: Sequence[str] = (),
    ) -> ActionHandle:
        binding = NeuronActionBinding(
            name=name,
            label=label,
            fn=fn,
            resets_fields=resets_fields,
            shortcuts=tuple(shortcuts),
        )
        self._add_action(binding)
        return ActionHandle(binding)

    def interactions(
        self,
        *,
        entity_click: ClickHandler | None = None,
        key_press: KeyHandler | None = None,
        capture_trace: ClickHandler | None = None,
    ) -> None:
        """Register source-level interaction behavior."""

        if entity_click is None and key_press is None and capture_trace is None:
            raise ValueError("interactions(...) requires at least one handler")
        if entity_click is not None:
            self._click_handlers.append(entity_click)
        if key_press is not None:
            self._key_handlers.append(key_press)
        if capture_trace is not None:
            self._capture_predicate = capture_trace

    def state(self, key: str, value: Any) -> None:
        """Seed an initial binding-namespace value (resolved against the backend if callable)."""
        self._initial_state.append((key, value))

    def layout(self, rows: Sequence[Sequence[str | PanelHandle]]) -> None:
        self._panel_grid = tuple(
            tuple(item.id if isinstance(item, PanelHandle) else str(item) for item in row)
            for row in rows
        )

    # -- registration helpers (used by attach-specific bindings) --------------

    def _add_field(self, build_field: Callable[[NeuronBackend], FieldSpec]) -> None:
        self._fields.append(build_field)

    def _add_view(self, view: Any) -> None:
        self._views.append(view)

    def _add_panel(self, panel: PanelSpec) -> None:
        self._panels.append(panel)

    def _add_extra_control(self, control_spec: ControlSpec) -> None:
        self._extra_controls[control_spec.id] = control_spec

    # -- AppSpec assembly -----------------------------------------------------

    def _build_app_spec_for_backend(self, backend: BackendBase) -> AppSpec:
        if not isinstance(backend, NeuronBackend):
            raise TypeError(f"{type(self).__name__} expected NeuronBackend, got {type(backend).__name__}")
        return self._compose_app_spec(backend, backend.build_startup_data())

    def _compose_app_spec(self, backend: NeuronBackend, base_app_spec: AppSpec) -> AppSpec:
        fields = dict(base_app_spec.data.fields)
        views = dict(base_app_spec.view_catalog.views)
        controls = dict(base_app_spec.interactions.controls)
        actions = dict(base_app_spec.interactions.actions)
        panels = list(self._panels)

        for build_field in self._fields:
            field = build_field(backend)
            fields[field.id] = field
        for item in self._views:
            view = item(backend) if callable(item) else item
            views[view.id] = view

        controls.update(self._extra_controls)
        extra_control_ids = tuple(self._extra_controls)

        backend_control_ids: tuple[str, ...] = ()
        action_ids: tuple[str, ...] = ()
        if self._include_controls:
            backend_controls = backend.control_specs()
            backend_actions = backend._resolved_action_specs()
            controls.update(backend_controls)
            actions.update(backend_actions)
            backend_control_ids = tuple(backend_controls) if self._control_ids is None else tuple(
                item for item in self._control_ids if item in backend_controls
            )
            preferred_actions = self._action_ids
            if preferred_actions is None:
                preferred_actions = backend._resolved_action_order(backend_actions)
            action_ids = tuple(backend_actions) if preferred_actions is None else tuple(
                item for item in preferred_actions if item in backend_actions
            )

        control_ids = tuple(dict.fromkeys((*extra_control_ids, *backend_control_ids)))
        if control_ids or action_ids:
            panels.append(
                PanelSpec(
                    id=self._controls_panel_id,
                    kind=PANEL_KIND_CONTROLS,
                    control_ids=control_ids,
                    action_ids=action_ids,
                )
            )

        panel_grid = self._panel_grid or tuple((panel.id,) for panel in panels)
        composed = AppSpec(
            data=DataCatalog(fields=fields, geometries=dict(base_app_spec.data.geometries)),
            view_catalog=ViewCatalog(views=views, operators=dict(base_app_spec.view_catalog.operators)),
            interactions=InteractionCatalog(controls=controls, actions=actions),
            layout_catalog=LayoutCatalog.single(
                LayoutSpec(
                    title=self.title,
                    panels=tuple(panels),
                    panel_grid=panel_grid,
                )
            ),
            metadata=base_app_spec.metadata,
        )
        return append_bindings_to_app_spec(
            composed,
            traces=self._traces,
            controls=self._controls,
            actions=self._actions,
        )


__all__ = [
    "LineRecorder",
    "NeuronActionBinding",
    "NeuronControlBinding",
    "NeuronInlineSource",
    "PanelHandle",
]
