"""Shared inline-authoring composition layer for NEURON sources.

``NeuronSource`` wraps raw sections and declares views and panels over the
fields their backend emits. That vocabulary -- ``morphology``, ``history``,
``line``, ``state_graph``, ``controls``, ``layout`` -- is backend-agnostic and
lives here once so AppSpec composition stays separate from source-specific
runtime sampling.
"""

from __future__ import annotations

import bisect
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from compneurovis.backends.base import BackendBase
from compneurovis.backends.neuron.backend import (
    DISPLAY_FIELD_ID,
    HISTORY_FIELD_ID,
    DisplayConfig,
    NeuronBackend,
)
from compneurovis.backends.interaction import (
    SELECTED_ENTITY_IDS_KEY,
    _selection_to_internal,
)
from compneurovis.core.app_spec import AppSpec
from compneurovis.core.controls import (
    ActionSpec,
    ControlPresentationSpec,
    ControlSpec,
    ControlValueSpec,
    ScalarValueSpec,
)
from compneurovis.core.field import FieldSpec
from compneurovis.core.state import StateBindingSpec
from compneurovis.inline.bindings import (
    ActionBinding,
    ActionHandle,
    ControlBinding,
    ControlHandle,
    FieldSource,
    LinePlotWidget,
    MorphologyWidget,
    PanelHandle,
    SpecWidget,
    ValueRef,
    append_bindings_to_app_spec,
)
from compneurovis.inline.sources import InlineSourceBase

# Callable arities accepted by interaction-hook functions. Hooks are invoked
# with as many positional args as they declare, so authors can write
# ``fn()``, ``fn(ctx)``, or ``fn(ctx, payload)`` and get only what they ask for.
ClickHandler = Callable[..., Any]
KeyHandler = Callable[..., Any]
SampleFn = Callable[[], Any]
_MISSING = object()

# Sentinel for view metadata that should inherit from the declared display field
@dataclass(frozen=True, slots=True)
class SelectionRef:
    """Handle to morphology selection.

    Runtime state under ``key`` is always a list. Interaction contexts expose it
    as a scalar/None for single-select and as a list for multi-select.
    """

    key: str
    select_multiple: bool = False
    _is_selection_ref: bool = True


@dataclass(frozen=True, slots=True)
class MorphologyHandle(PanelHandle):
    """Panel handle for a morphology and selected-trace source."""

    selection: FieldSource
    selected: SelectionRef


def _value_key(value: str | ValueRef | SelectionRef) -> str:
    return value.key if isinstance(value, (ValueRef, SelectionRef)) else str(value)


def _resolve_selectors(selectors: Mapping[str, Any]) -> dict[str, Any]:
    return {
        dim: StateBindingSpec(value.key) if isinstance(value, (ValueRef, SelectionRef)) else value
        for dim, value in selectors.items()
    }



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
        self.set(backend._interaction_context(), value)
        return True


@dataclass
class NeuronActionBinding(ActionBinding):
    """Inline action whose handler is called with the interaction context.

    Carries shortcut keys so the action can also fire from the keyboard, and is
    dispatched with an interaction context -- resolving the zero-arg-action gap
    so actions can show status, set selection state, or invoke other actions.
    """

    shortcuts: tuple[str, ...] = ()

    def _action_spec(self) -> ActionSpec:
        return ActionSpec(id=self._action_id, label=self.label, shortcuts=tuple(self.shortcuts))

    def invoke(self, context: Any, payload: dict[str, Any]) -> None:
        del payload
        self.fn(context)


@dataclass
class LineRecorder:
    """Per-tick sampler feeding a declared ``line(...)`` field.

    The source backend calls ``sample()`` once per integration step, stacks the
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


@dataclass
class DerivedField:
    """A value computed from the live sim each frame.

    Sampling and evaluation are split for performance: when ``over`` is set, the
    backend appends ``over()`` to a rolling ``window`` (ms) every frame — cheap —
    and calls ``fn(t, v)`` only when ``max_refresh_hz`` is due. With no ``over``,
    ``fn()`` returns the current value(s) directly. ``target="field"`` emits a
    field (append: a time series; replace: a snapshot vector); ``target="value"``
    publishes one runtime value under ``name``.
    """

    name: str
    fn: Callable[..., Any]
    target: str  # "field" | "value"
    field_id: str
    series: tuple[str, ...]
    series_dim: str
    mode: str  # "append" | "replace"
    over: SampleFn | None
    window: float
    max_refresh_hz: float | None
    max_samples: int = 5000
    _times: list[float] = field(default_factory=list)
    _values: list[np.ndarray] = field(default_factory=list)
    _last_eval_s: float = field(default=float("-inf"))

    def observe(self, t: float) -> None:
        if self.over is None:
            return
        self._times.append(float(t))
        self._values.append(np.asarray(self.over(), dtype=np.float64).copy())
        if self._times[0] < self._times[-1] - self.window:
            cut = bisect.bisect_left(self._times, self._times[-1] - self.window)
            if cut > 0:
                del self._times[:cut]
                del self._values[:cut]

    def due(self, now: float) -> bool:
        interval = (1.0 / self.max_refresh_hz) if self.max_refresh_hz and self.max_refresh_hz > 0 else 0.0
        return (now - self._last_eval_s) >= interval

    def evaluate(self, now: float) -> Any:
        if self.over is not None:
            if len(self._times) < 2:
                return None
            self._last_eval_s = now
            return self.fn(
                np.asarray(self._times, dtype=np.float64),
                np.asarray(self._values, dtype=np.float64),
            )
        self._last_eval_s = now
        return self.fn()

    def field_values(self, result: Any) -> np.ndarray:
        return np.asarray(result, dtype=np.float32).reshape(len(self.series))

    def reset(self) -> None:
        self._times.clear()
        self._values.clear()
        self._last_eval_s = float("-inf")


class NeuronInlineSource(InlineSourceBase):
    """Shared composition vocabulary for NEURON inline sources.

    Subclasses provide ``_make_backend``; everything below -- view/panel
    declaration and AppSpec assembly -- is shared by source-owned source
    variants.
    """

    def __init__(self, *, title: str = "CompNeuroVis") -> None:
        super().__init__(title=title)
        # Every declared widget (morphology, line, history, ...) is one SpecWidget
        # in this list -- the same uniform contribution path as generic widgets.
        self._panel_bindings: list[Any] = []
        self._panel_grid: tuple[tuple[str, ...], ...] | None = None
        self._controls_panel_id = "controls-panel"
        # Runtime hooks, executed by the source-owned backend.
        self._recorders: list[LineRecorder] = []
        self._click_handlers: list[ClickHandler] = []
        self._key_handlers: list[KeyHandler] = []
        self._capture_predicate: ClickHandler | None = None
        self._initial_state: list[tuple[str, Any]] = []
        self._derives: list[DerivedField] = []
        self._control_hooks: list[Callable[..., Any]] = []
        # The per-segment scalar the morphology renders, set by morphology(). The
        # generic line(source=morph.selection) plots it over time. No implicit default.
        self._display: DisplayConfig | None = None

    # -- authoring vocabulary -------------------------------------------------

    def morphology(
        self,
        *,
        variable: str | Callable[[Any], Any],
        name: str = "Morphology",
        unit: str | None = None,
        color_limits: tuple[float, float] | None = None,
        color_map: str = "scalar",
        color_norm: str = "auto",
        label: str | None = None,
        color_field_id: str | None = None,
        background_color: Any = "white",
        max_refresh_hz: float | None = None,
        selected: Any = None,
        selectable: bool = True,
        select_multiple: bool = False,
        panel: bool = True,
    ) -> MorphologyHandle:
        """Render a per-segment scalar over the morphology.

        ``variable`` is a NEURON range-variable name (read as ``seg._ref_<var>``)
        or a callable ``seg -> ref`` — explicit, no privileged default. Voltage is
        just ``morphology(variable="v", unit="mV", ...)``.

        ``selectable=False`` makes the panel visual-only: clicks do not emit
        entity selection. ``selected`` initializes the selection: pass one entity
        id for single-select, or an iterable of ids when ``select_multiple=True``.
        ``None`` or an empty iterable means no selected trace. Internally the
        selection is always stored as a list, and the returned handle's
        ``.selection`` is a :class:`FieldSource` over that list.

        ``panel=False`` declares the display variable + selection source but adds
        no 3D panel (no canvas). Useful for headless/sweep contexts, or to isolate
        the 3D-draw cost while keeping the same backend data stream.
        """
        if select_multiple and not selectable:
            raise ValueError("morphology(select_multiple=True) requires selectable=True")

        if callable(variable):
            ref_of = variable
        else:
            var_name = str(variable)
            ref_of = lambda seg, _n=var_name: getattr(seg, f"_ref_{_n}")
        self._display = DisplayConfig(
            ref_of=ref_of,
            unit=unit,
            color_limits=color_limits,
            color_map=color_map,
            color_norm=color_norm,
            label=label,
            selected_entity_ids=tuple(_selection_to_internal(selected, select_multiple=select_multiple)),
            select_multiple=select_multiple,
        )
        selection_key = SELECTED_ENTITY_IDS_KEY
        slug = _slug(name)
        view_id = slug
        panel_id = f"{slug}-panel"
        if panel:
            self._panel_bindings.append(
                MorphologyWidget(
                    view_id=view_id,
                    panel_id=panel_id,
                    title=name,
                    geometry_id=lambda backend: backend.geometry.id,
                    color_field_id=color_field_id or DISPLAY_FIELD_ID,
                    entity_dim="segment",
                    sample_dim=None,
                    selectable=selectable,
                    style={
                        "color_map": color_map,
                        "color_limits": color_limits,
                        "color_norm": color_norm,
                        "background_color": background_color,
                        "max_refresh_hz": max_refresh_hz,
                    },
                )
            )
        return MorphologyHandle(
            id=panel_id,
            selection=FieldSource(
                field_id=HISTORY_FIELD_ID,
                series_dim="segment",
                selectors={"segment": StateBindingSpec(selection_key)},
                unit=unit,
            ),
            selected=SelectionRef(selection_key, select_multiple=select_multiple),
        )

    def line(
        self,
        name: str,
        *,
        source: FieldSource | None = None,
        field_id: str | None = None,
        series: Sequence[str] | None = None,
        initial: Callable[[NeuronBackend], Any] | Sequence[float] | np.ndarray | None = None,
        record: SampleFn | None = None,
        max_samples: int = 5000,
        unit: str | None = None,
        x: str | None = "time",
        by: str | None = None,
        select: Mapping[str, Any] | None = None,
        levels: Sequence[Any] = (),
        panel_id: str | None = None,
        **style: Any,
    ) -> PanelHandle:
        """Declare a line plot.

        Field-backed lines are generic and delegated to ``InlineSourceBase``.
        NEURON-specific work lives here only when a recorder-backed field must be
        created and sampled in the integration loop.
        """
        if record is None and series is None and initial is None:
            resolved_select = _resolve_selectors(select) if select is not None else None
            if unit is not None and "y_unit" not in style:
                style = {**style, "y_unit": unit}
            return super().line(
                name,
                source=source,
                field_id=field_id,
                x=x,
                by=by,
                select=resolved_select,
                levels=levels,
                panel_id=panel_id,
                **style,
            )

        if source is not None:
            raise ValueError("line(record=.../series=...) creates a NEURON field; omit source=...")
        if series is None:
            raise ValueError("line(record=.../initial=...) requires series=[...] to name channels")
        if record is None and initial is None:
            raise ValueError("line(series=...) requires record=... or initial=...")

        slug = _slug(name)
        resolved_field_id = field_id or f"{slug}_field"
        view_id = f"{slug}_plot"
        resolved_panel_id = panel_id or f"{slug}-panel"
        series_dim = by or "series"
        selectors = _resolve_selectors(select or {})
        labels = tuple(str(item) for item in series)

        def build_field(backend: NeuronBackend) -> FieldSpec:
            if initial is not None:
                raw: Any = initial(backend) if callable(initial) else initial
            elif record is not None:
                raw = record()
            else:
                raw = np.zeros((len(labels), 1), dtype=np.float32)
            values = _coerce_series_initial(raw, len(labels))
            return FieldSpec(
                id=resolved_field_id,
                initial_values=values,
                dims=(series_dim, "time"),
                coords={series_dim: np.asarray(labels), "time": _time_coord(backend)},
                unit=unit,
            )

        if record is not None:
            self._recorders.append(
                LineRecorder(
                    field_id=resolved_field_id,
                    series_dim=series_dim,
                    series=labels,
                    sample=record,
                    max_samples=max_samples,
                )
            )

        if unit is not None and "y_unit" not in style:
            style = {**style, "y_unit": unit}
        title = style.pop("title", name)
        self._panel_bindings.append(
            LinePlotWidget(
                field_id=resolved_field_id,
                view_id=view_id,
                panel_id=resolved_panel_id,
                title=title,
                x_dim=x,
                series_dim=series_dim,
                selectors=selectors,
                levels=levels,
                field_builders=(build_field,),
                style=style,
            )
        )
        return PanelHandle(resolved_panel_id)

    @property
    def controls_panel(self) -> PanelHandle:
        """Handle for the controls panel, for use in ``cnv.layout``."""
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

    def create_value(self, name: str | ValueRef, *, initial: Any = _MISSING) -> ValueRef:
        """Declare a runtime value handle, optionally with an initial value."""
        ref = ValueRef(_value_key(name))
        if initial is not _MISSING:
            self._initial_state.append((ref.key, initial))
        return ref

    def derive(
        self,
        name: str,
        fn: Callable[..., Any],
        *,
        over: SampleFn | None = None,
        window: float = 2000.0,
        series: Sequence[str] | None = None,
        by: str | None = None,
        mode: str = "append",
        max_refresh_hz: float | None = 10.0,
        max_samples: int = 5000,
        unit: str | None = None,
    ) -> FieldSource:
        """Compute a field from the live sim.

        ``fn`` is your metric/classifier. With ``over=<signal>`` the backend
        buffers ``window`` ms of that signal and calls ``fn(t, v)``; otherwise
        ``fn()`` returns the current value(s). Returns a :class:`FieldSource` to
        feed ``line(source=...)``/``bar(source=...)``. Evaluation is throttled by
        ``max_refresh_hz`` independently of sampling.
        """
        if mode not in ("append", "replace"):
            raise ValueError("derive(mode=...) must be 'append' or 'replace'")

        labels = tuple(str(item) for item in (series if series is not None else (name,)))
        series_dim = by or "series"
        field_id = f"{_slug(name)}_field"
        self._derives.append(
            DerivedField(
                name=name, fn=fn, target="field", field_id=field_id, series=labels,
                series_dim=series_dim, mode=mode, over=over, window=window,
                max_refresh_hz=max_refresh_hz, max_samples=max_samples,
            )
        )

        def build_field(backend: NeuronBackend) -> FieldSpec:
            raw: Any = None
            if over is None:
                try:
                    raw = np.asarray(fn(), dtype=np.float32).reshape(len(labels))
                except Exception:
                    raw = None
            base = np.zeros(len(labels), dtype=np.float32) if raw is None else raw
            if mode == "append":
                return FieldSpec(
                    id=field_id,
                    initial_values=base.reshape(len(labels), 1),
                    dims=(series_dim, "time"),
                    coords={series_dim: np.asarray(labels), "time": _time_coord(backend)},
                    unit=unit,
                )
            return FieldSpec(
                id=field_id,
                initial_values=base,
                dims=(series_dim,),
                coords={series_dim: np.asarray(labels)},
                unit=unit,
            )

        self._add_widget(field_builders=(build_field,))
        return FieldSource(field_id=field_id, series_dim=series_dim, selectors={}, unit=unit)

    def derive_value(
        self,
        name: str,
        fn: Callable[..., Any],
        *,
        over: SampleFn | None = None,
        window: float = 2000.0,
        max_refresh_hz: float | None = 10.0,
        initial: Any = _MISSING,
    ) -> ValueRef:
        """Compute one runtime value from the live sim."""
        ref = self.create_value(name, initial=initial) if initial is not _MISSING else ValueRef(str(name))
        self._derives.append(
            DerivedField(
                name=ref.key,
                fn=fn,
                target="value",
                field_id="",
                series=(),
                series_dim="",
                mode="replace",
                over=over,
                window=window,
                max_refresh_hz=max_refresh_hz,
            )
        )
        return ref

    def on_control(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Register a hook ``fn(control_id, value)`` run on every control change
        after the backend accepts it. A third ``ctx`` argument is optional for
        recording helpers that need ``ctx.controls()`` or ``ctx.get_value(...)``."""
        self._control_hooks.append(fn)
        return fn

    # -- registration helper (used by source-specific bindings) ---------------

    def _add_widget(
        self,
        *,
        field_builders: Sequence[Any] = (),
        views: Sequence[Any] = (),
        panel: Any = None,
        controls: Sequence[Any] = (),
    ) -> None:
        """Register one declared widget as a uniform SpecWidget contribution."""
        self._panel_bindings.append(
            SpecWidget(
                field_builders=tuple(field_builders),
                views=tuple(views),
                panel=panel,
                controls=tuple(controls),
            )
        )

    # -- AppSpec assembly -----------------------------------------------------

    def _uses_history_field(self) -> bool:
        for widget in (*self._widgets, *self._panel_bindings):
            if getattr(widget, "field_id", None) == HISTORY_FIELD_ID:
                return True
            if getattr(widget, "color_field_id", None) == HISTORY_FIELD_ID:
                return True
            for view in getattr(widget, "views", ()):
                if callable(view):
                    continue
                if getattr(view, "field_id", None) == HISTORY_FIELD_ID:
                    return True
                if getattr(view, "color_field_id", None) == HISTORY_FIELD_ID:
                    return True
        return False

    def _compose_app_spec_for_backend(self, backend: BackendBase) -> AppSpec:
        if not isinstance(backend, NeuronBackend):
            raise TypeError(f"{type(self).__name__} expected NeuronBackend, got {type(backend).__name__}")
        backend.set_history_enabled(self._uses_history_field())
        return append_bindings_to_app_spec(
            backend.build_startup_data(),
            panel_bindings=(*self._widgets, *self._panel_bindings, *self._traces),
            controls=self._controls,
            actions=self._actions,
            backend=backend,
        )


__all__ = [
    "DerivedField",
    "LineRecorder",
    "MorphologyHandle",
    "SelectionRef",
    "NeuronActionBinding",
    "NeuronControlBinding",
    "NeuronInlineSource",
    "PanelHandle",
    "ValueRef",
]
