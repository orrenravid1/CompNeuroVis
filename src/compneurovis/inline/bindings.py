"""Binding and handle objects for inline-mode source registration."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from compneurovis.backends.base import BackendBase
from compneurovis.core.app_spec import (
    AppSpec,
    DataCatalog,
    InteractionCatalog,
    LayoutCatalog,
    LayoutSpec,
    PanelSpec,
    PANEL_KIND_CONTROLS,
    PANEL_KIND_BAR_PLOT,
    PANEL_KIND_LINE_PLOT,
    PANEL_KIND_STATE_GRAPH,
    PANEL_KIND_VIEW_3D,
    ViewCatalog,
)
from compneurovis.core.controls import ActionSpec, ControlPresentationSpec, ControlSpec, ControlValueSpec, ScalarValueSpec
from compneurovis.core.field import FieldSpec
from compneurovis.core.geometry import GridGeometrySpec
from compneurovis.core.messages import FieldAppend, FieldReplace, update_message
from compneurovis.core.operators import GridSliceOperatorSpec
from compneurovis.core.values import ValueBindingSpec
from compneurovis.core.views import BarPlotViewSpec, LevelMarker, LinePlotViewSpec, MorphologyViewSpec, StateGraphViewSpec, SurfaceViewSpec

SeriesReaders = Callable[[], float] | Mapping[str, Callable[[], float]]


def _slug(value: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in str(value).strip()).strip("_").lower() or "item"


@dataclass(frozen=True)
class FieldSource:
    """Reference to an existing field for a plot widget."""

    field_id: str
    series_dim: str | None = None
    selectors: Mapping[str, Any] = field(default_factory=dict)
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class PanelHandle:
    id: str


@dataclass(frozen=True, slots=True)
class SelectionRef:
    """Handle to morphology selection state."""

    key: str
    select_multiple: bool = False
    _is_selection_ref: bool = True


@dataclass(frozen=True, slots=True)
class MorphologyHandle(PanelHandle):
    """Panel handle for a morphology view."""

    selected: SelectionRef
    selection: FieldSource | None = None


@dataclass(frozen=True, slots=True)
class ValueRef:
    key: str


def _binding_key(value: Any) -> str:
    if isinstance(value, ControlHandle):
        return value.value_key
    if isinstance(value, ValueRef):
        return value.key
    return str(value)


def bind(value: Any) -> Any:
    """Lower inline handles to runtime state bindings."""

    if isinstance(value, (ControlHandle, SelectionRef, ValueRef)):
        return ValueBindingSpec(_binding_key(value))
    return value


def _to_level(item: Any, default_orientation: str) -> LevelMarker:
    if isinstance(item, LevelMarker):
        return item
    if isinstance(item, (ControlHandle, ValueRef)):
        return LevelMarker(value=ValueBindingSpec(_binding_key(item)), orientation=default_orientation)
    if isinstance(item, str):
        return LevelMarker(value=ValueBindingSpec(item), orientation=default_orientation)
    if isinstance(item, ValueBindingSpec):
        return LevelMarker(value=item, orientation=default_orientation)
    return LevelMarker(value=float(item), orientation=default_orientation)


@dataclass(frozen=True)
class PanelContribution:
    """What a widget adds to the app-spec: a uniform, immutable record.

    Every widget -- generic (trace/surface/grid-slice) or backend (neuron/jaxley
    morphology, history, ...) -- describes itself by returning one of these from
    ``contribution(backend)``. The assembler merges them uniformly, so no source
    special-cases how a widget of a given shape is stitched in. ``controls`` is
    reserved for pre-built low-level specs; source-level UI should normally be
    declared with typed calls like ``source.slider(...)`` or
    ``source.checkbox(...)``. ``panel`` is this widget's own panel,
    if it has one.
    """

    fields: tuple = ()
    geometries: tuple = ()
    views: tuple = ()
    operators: tuple = ()
    controls: tuple = ()
    panel: Any = None


@dataclass(frozen=True)
class StartupData:
    """Simulator startup data before any source-declared views/panels exist."""

    fields: tuple = ()
    geometries: tuple = ()
    title: str = "CompNeuroVis"
    metadata: Mapping[str, Any] | None = None

    def app_spec(self) -> AppSpec:
        return AppSpec(
            data=DataCatalog(
                fields={field.id: field for field in self.fields},
                geometries={geometry.id: geometry for geometry in self.geometries},
            ),
            view_catalog=ViewCatalog(views={}),
            interactions=InteractionCatalog(controls={}, actions={}),
            layout_catalog=LayoutCatalog.single(LayoutSpec(title=self.title, panels=(), panel_grid=())),
            metadata={} if self.metadata is None else dict(self.metadata),
        )

@dataclass
class SpecWidget:
    """Widget whose specs are pre-built, or built from the backend at compose.

    Backend sources (neuron, jaxley) declare morphology/history/ref-line panels
    whose field specs must be sampled from the live model. Wrapping each as a
    ``SpecWidget`` lets them flow through the same uniform ``contribution(backend)``
    path as the generic widgets -- one widget, one panel, no bespoke compose.
    ``field_builders`` / ``geometries`` / ``views`` entries may each be a spec or a callable
    ``backend -> spec``.
    """

    field_builders: tuple = ()
    geometries: tuple = ()
    views: tuple = ()
    panel: Any = None
    controls: tuple = ()

    def contribution(self, backend: Any = None) -> PanelContribution:
        return PanelContribution(
            fields=tuple(f(backend) if callable(f) else f for f in self.field_builders),
            geometries=tuple(g(backend) if callable(g) else g for g in self.geometries),
            views=tuple(v(backend) if callable(v) else v for v in self.views),
            panel=self.panel,
            controls=self.controls,
        )




@dataclass
class ArrayFieldBinding:
    """A 1-D field the source owns outright.

    Gives ``bar`` and ``state_graph`` the same data vocabulary as ``surface``:
    literal ``values`` for a static field, or a ``read`` callable resampled every
    tick. Widgets plotting a field somebody else declares take ``source=`` instead.
    """

    field_id: str
    dim: str
    labels: tuple[str, ...]
    values: Any = None
    read: Callable[[], Any] | None = None
    unit: str | None = None

    def resolve(self) -> np.ndarray:
        raw = self.read() if self.read is not None else self.values
        array = np.asarray(raw, dtype=np.float32).reshape(-1)
        if array.size != len(self.labels):
            raise ValueError(
                f"field {self.field_id!r} expects {len(self.labels)} values "
                f"over dim {self.dim!r}, got {array.size}"
            )
        return array

    def field_spec(self) -> FieldSpec:
        return FieldSpec(
            id=self.field_id,
            initial_values=self.resolve(),
            dims=(self.dim,),
            coords={self.dim: np.asarray(self.labels)},
            unit=self.unit,
        )

    def replace_payload(self) -> FieldReplace:
        return FieldReplace(field_id=self.field_id, values=self.resolve())


def _level_items(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, LevelMarker, ValueBindingSpec, ControlHandle, ValueRef)):
        return (value,)
    try:
        return tuple(value)
    except TypeError:
        return (value,)

@dataclass
class LinePlotWidget:
    """Shared line-plot view + panel builder.

    Data production stays with each source/backend. This widget only describes
    how an already-declared field or operator should appear as a line plot.
    """

    view_id: str
    panel_id: str
    title: Any
    field_id: str | None = None
    operator_id: str | None = None
    x_dim: str | None = "time"
    series_dim: str | None = None
    selectors: Mapping[str, Any] = field(default_factory=dict)
    levels: Sequence[Any] = ()
    field_builders: tuple = ()
    panel_title: str | None = None
    style: Mapping[str, Any] = field(default_factory=dict)

    def contribution(self, backend: Any = None) -> PanelContribution:
        return PanelContribution(
            fields=tuple(builder(backend) if callable(builder) else builder for builder in self.field_builders),
            views=(self.view_spec(),),
            panel=self.panel_spec(),
        )

    def view_spec(self) -> LinePlotViewSpec:
        kwargs = {key: bind(value) for key, value in self.style.items()}
        style_levels = kwargs.pop("levels", ())
        levels = tuple(
            _to_level(item, "horizontal")
            for item in (*_level_items(self.levels), *_level_items(style_levels))
        )
        selectors = {dim: bind(value) for dim, value in self.selectors.items()}
        return LinePlotViewSpec(
            id=self.view_id,
            title=bind(self.title),
            field_id=self.field_id or "",
            operator_id=self.operator_id,
            x_dim=self.x_dim,
            series_dim=self.series_dim,
            selectors=selectors,
            levels=levels,
            **kwargs,
        )

    def panel_spec(self) -> PanelSpec:
        return PanelSpec(
            id=self.panel_id,
            kind=PANEL_KIND_LINE_PLOT,
            view_ids=(self.view_id,),
            title=self.panel_title,
        )


@dataclass
class MorphologyWidget:
    """Shared morphology view + panel builder."""

    view_id: str
    panel_id: str
    title: Any
    geometry_id: str | Callable[[Any], str]
    color_field_id: str | None = None
    entity_dim: str = "segment"
    sample_dim: str | None = None
    selectable: bool = True
    style: Mapping[str, Any] = field(default_factory=dict)

    def contribution(self, backend: Any = None) -> PanelContribution:
        return PanelContribution(views=(self.view_spec(backend),), panel=self.panel_spec())

    def view_spec(self, backend: Any = None) -> MorphologyViewSpec:
        geometry_id = self.geometry_id(backend) if callable(self.geometry_id) else self.geometry_id
        kwargs = {key: bind(value) for key, value in self.style.items()}
        return MorphologyViewSpec(
            id=self.view_id,
            title=bind(self.title),
            geometry_id=geometry_id,
            color_field_id=self.color_field_id,
            entity_dim=self.entity_dim,
            sample_dim=self.sample_dim,
            selectable=self.selectable,
            **kwargs,
        )

    def panel_spec(self) -> PanelSpec:
        return PanelSpec(id=self.panel_id, kind=PANEL_KIND_VIEW_3D, view_ids=(self.view_id,))


@dataclass
class BarPlotWidget:
    """Shared bar-plot view + panel builder."""

    field_id: str
    view_id: str
    panel_id: str
    title: Any
    category_dim: str | None = "series"
    levels: Sequence[Any] = ()
    field_builders: tuple = ()
    style: Mapping[str, Any] = field(default_factory=dict)

    def contribution(self, backend: Any = None) -> PanelContribution:
        return PanelContribution(
            fields=tuple(builder(backend) if callable(builder) else builder for builder in self.field_builders),
            views=(self.view_spec(),),
            panel=self.panel_spec(),
        )

    def view_spec(self) -> BarPlotViewSpec:
        kwargs = {key: bind(value) for key, value in self.style.items()}
        style_levels = kwargs.pop("levels", ())
        levels = tuple(
            _to_level(item, "vertical")
            for item in (*_level_items(self.levels), *_level_items(style_levels))
        )
        return BarPlotViewSpec(
            id=self.view_id,
            title=bind(self.title),
            field_id=self.field_id,
            category_dim=self.category_dim,
            levels=levels,
            **kwargs,
        )

    def panel_spec(self) -> PanelSpec:
        return PanelSpec(id=self.panel_id, kind=PANEL_KIND_BAR_PLOT, view_ids=(self.view_id,))


@dataclass
class StateGraphWidget:
    """Shared state-graph view + panel builder."""

    view_id: str
    panel_id: str
    title: Any
    node_field_id: str
    edge_field_id: str
    node_positions: tuple[tuple[str, float, float], ...]
    edges: tuple[tuple[str, str, str], ...]
    field_builders: tuple = ()
    style: Mapping[str, Any] = field(default_factory=dict)

    def contribution(self, backend: Any = None) -> PanelContribution:
        return PanelContribution(
            fields=tuple(builder(backend) if callable(builder) else builder for builder in self.field_builders),
            views=(self.view_spec(),),
            panel=self.panel_spec(),
        )

    def view_spec(self) -> StateGraphViewSpec:
        kwargs = {key: bind(value) for key, value in self.style.items()}
        return StateGraphViewSpec(
            id=self.view_id,
            title=bind(self.title),
            node_field_id=self.node_field_id,
            edge_field_id=self.edge_field_id,
            node_positions=self.node_positions,
            edges=self.edges,
            **kwargs,
        )

    def panel_spec(self) -> PanelSpec:
        return PanelSpec(id=self.panel_id, kind=PANEL_KIND_STATE_GRAPH, view_ids=(self.view_id,))

@dataclass
class TraceBinding:
    name: str
    read: SeriesReaders
    x: Callable[[], float] | None = None
    title: str | None = None
    rolling_window: float = 500.0
    trim_to_rolling_window: bool = True
    y_min: float | None = None
    y_max: float | None = None
    y_unit: str = "a.u."
    x_unit: str = "ms"
    x_label: str = "Time"
    y_label: str = "Value"
    color: Any = "k"
    background_color: Any = "w"
    show_legend: bool | None = None
    colors: Any = field(default_factory=dict)
    linestyle: Any = "-"
    linestyles: Any = field(default_factory=dict)
    linewidth: Any = 2.0
    linewidths: Any = field(default_factory=dict)
    max_refresh_hz: float | None = None
    x_major_tick_spacing: float | None = None
    x_minor_tick_spacing: float | None = None
    levels: Sequence[Any] = ()
    max_samples: int = 2400
    _field_id: str = field(init=False, default="")
    _view_id: str = field(init=False, default="")
    _panel_id: str = field(init=False, default="")
    _buf_x: list = field(init=False, default_factory=list)
    _buf_vals: list = field(init=False, default_factory=list)
    _sampled_this_frame: bool = field(init=False, default=False)

    def _register(self, index: int) -> None:
        slug = _slug(self.name)
        self._field_id = f"field_{index}_{slug}"
        self._view_id = f"view_{index}_{slug}"
        self._panel_id = f"panel_{index}_{slug}"

    def _series(self) -> dict[str, Callable[[], float]]:
        if callable(self.read):
            return {self.name: self.read}
        return dict(self.read)

    def _begin_frame(self) -> None:
        self._sampled_this_frame = False

    def _sample(self) -> None:
        series = self._series()
        self._buf_x.append(self._x_value())
        self._buf_vals.append([fn() for fn in series.values()])
        self._sampled_this_frame = True

    def _x_value(self) -> float:
        if self.x is not None:
            return float(self.x())
        return float(len(self._buf_x))

    def _drain_message(self):
        if not self._buf_x:
            return None
        xs = self._buf_x[:]
        vals = self._buf_vals[:]
        self._buf_x.clear()
        self._buf_vals.clear()
        n_series = len(self._series())
        values = np.array(vals, dtype=np.float32).reshape(len(xs), n_series).T
        return update_message(
            FieldAppend(
                field_id=self._field_id,
                append_dim="time",
                values=values,
                coord_values=np.array(xs, dtype=np.float32),
                max_length=self.max_samples,
            )
        )

    def _field_spec(self) -> FieldSpec:
        series = self._series()
        return FieldSpec(
            id=self._field_id,
            initial_values=np.array([[fn()] for fn in series.values()], dtype=np.float32),
            dims=("series", "time"),
            coords={
                "series": np.array(list(series.keys())),
                "time": np.array([self._x_value()], dtype=np.float32),
            },
            unit=self.y_unit,
        )

    def contribution(self, backend: Any = None) -> PanelContribution:
        del backend
        widget = self._line_widget()
        return PanelContribution(
            fields=(self._field_spec(),),
            views=(widget.view_spec(),),
            panel=widget.panel_spec(),
        )

    def _line_widget(self) -> LinePlotWidget:
        series = self._series()
        return LinePlotWidget(
            field_id=self._field_id,
            view_id=self._view_id,
            panel_id=self._panel_id,
            title=self.title or self.name,
            x_dim="time",
            series_dim="series",
            levels=self.levels,
            style={
                "x_label": self.x_label,
                "y_label": self.y_label,
                "x_unit": self.x_unit,
                "y_unit": self.y_unit,
                "rolling_window": self.rolling_window,
                "trim_to_rolling_window": self.trim_to_rolling_window,
                "y_min": self.y_min,
                "y_max": self.y_max,
                "color": self.color,
                "background_color": self.background_color,
                "show_legend": len(series) > 1 if self.show_legend is None else self.show_legend,
                "colors": self.colors,
                "linestyle": self.linestyle,
                "linestyles": self.linestyles,
                "linewidth": self.linewidth,
                "linewidths": self.linewidths,
                "max_refresh_hz": self.max_refresh_hz,
                "x_major_tick_spacing": self.x_major_tick_spacing,
                "x_minor_tick_spacing": self.x_minor_tick_spacing,
            },
        )

    def _view_spec(self) -> LinePlotViewSpec:
        return self._line_widget().view_spec()

    def _panel_spec(self) -> PanelSpec:
        return self._line_widget().panel_spec()

    def _replace_message(self):
        series = self._series()
        values = np.array([[fn()] for fn in series.values()], dtype=np.float32)
        return update_message(
            FieldReplace(
                field_id=self._field_id,
                values=values,
                coords={
                    "series": np.array(list(series.keys())),
                    "time": np.array([self._x_value()], dtype=np.float32),
                },
            )
        )


@dataclass
class ControlBinding:
    name: str
    label: str
    get: Callable[[], Any] | None = None
    set: Callable[[Any, Any], None] | None = None
    min: float = 0.0
    max: float = 1.0
    default: Any = 0.0
    value_spec: ControlValueSpec | None = None
    presentation: ControlPresentationSpec | None = None
    send_to_backend: bool | None = None
    _control_id: str = field(init=False, default="")

    def _register(self, index: int) -> None:
        self._control_id = f"ctrl_{index}_{_slug(self.name)}"

    def _control_spec(self) -> ControlSpec:
        if self.value_spec is not None:
            value_spec = self.value_spec
        else:
            default = self.get() if self.get is not None else self.default
            value_spec = ScalarValueSpec(default=default, min=self.min, max=self.max)
        return ControlSpec(
            id=self._control_id,
            label=self.label,
            value_spec=value_spec,
            presentation=self.presentation,
            send_to_backend=(self.set is not None) if self.send_to_backend is None else self.send_to_backend,
        )

    def apply(self, backend: BackendBase, value: Any) -> bool:
        if self.set is not None:
            self.set(backend._interaction_context(), value)
        return True


@dataclass
class ActionBinding:
    """A named effect (``fn``) plus its triggers.

    ``show_button`` decides whether a button for it is placed in the controls
    panel; ``shortcuts`` are the keys that also invoke it. ``button(...)`` sets
    the former, ``hotkey(...)`` accumulates the latter -- both wire to this one
    effect. (Clearing plot history is a separate capability, ``ctx.clear(...)``,
    the effect calls when it wants it -- not a flag on the effect.)
    """

    name: str
    label: str
    fn: Callable[[Any], None]
    shortcuts: tuple[str, ...] = ()
    show_button: bool = True
    _action_id: str = field(init=False, default="")

    def _register(self, index: int) -> None:
        self._action_id = f"action_{index}_{_slug(self.name)}"

    def _action_spec(self) -> ActionSpec:
        return ActionSpec(id=self._action_id, label=self.label, shortcuts=tuple(self.shortcuts))


@dataclass
class SurfaceBinding:
    name: str
    values: Any
    x: Any | None = None
    y: Any | None = None
    read: Callable[[], Any] | None = None
    x_dim: str = "x"
    y_dim: str = "y"
    unit: str | None = None
    camera_distance: float | None = 30.0
    camera_elevation: float = 30.0
    camera_azimuth: float = 30.0
    view_kwargs: dict[str, Any] = field(default_factory=dict)
    _field_id: str = field(init=False, default="")
    _geometry_id: str = field(init=False, default="")
    _view_id: str = field(init=False, default="")
    _panel_id: str = field(init=False, default="")
    _operator_ids: list[str] = field(init=False, default_factory=list)

    def _register(self, index: int) -> None:
        slug = _slug(self.name)
        self._field_id = f"surface_{index}_{slug}_field"
        self._geometry_id = f"surface_{index}_{slug}_grid"
        self._view_id = f"surface_{index}_{slug}"
        self._panel_id = f"surface-panel-{index}-{slug}"

    def _values(self) -> np.ndarray:
        raw = self.read() if self.read is not None else self.values
        values = np.asarray(raw, dtype=np.float32)
        if values.ndim != 2:
            raise ValueError(f"surface({self.name!r}) values must be 2-D")
        return values

    def _coords(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        y_count, x_count = values.shape
        x = np.arange(x_count, dtype=np.float32) if self.x is None else np.asarray(self.x, dtype=np.float32)
        y = np.arange(y_count, dtype=np.float32) if self.y is None else np.asarray(self.y, dtype=np.float32)
        if x.ndim != 1 or y.ndim != 1:
            raise ValueError(f"surface({self.name!r}) x/y coords must be one-dimensional")
        if len(x) != x_count or len(y) != y_count:
            raise ValueError(
                f"surface({self.name!r}) coord lengths must match values shape; "
                f"got len(x)={len(x)}, len(y)={len(y)}, shape={values.shape}"
            )
        return x, y

    def _field_spec(self) -> FieldSpec:
        values = self._values()
        x, y = self._coords(values)
        return FieldSpec(
            id=self._field_id,
            initial_values=values,
            dims=(self.y_dim, self.x_dim),
            coords={self.y_dim: y, self.x_dim: x},
            unit=self.unit,
        )

    def contribution(self, backend: Any = None) -> PanelContribution:
        del backend
        return PanelContribution(
            fields=(self._field_spec(),),
            geometries=(self._geometry_spec(),),
            views=(self._view_spec(),),
            panel=self._panel_spec(),
        )

    def _geometry_spec(self) -> GridGeometrySpec:
        values = self._values()
        x, y = self._coords(values)
        return GridGeometrySpec(
            id=self._geometry_id,
            dims=(self.y_dim, self.x_dim),
            coords={self.y_dim: y, self.x_dim: x},
        )

    def _view_spec(self) -> SurfaceViewSpec:
        kwargs = {key: bind(value) for key, value in self.view_kwargs.items()}
        title = kwargs.pop("title", self.name)
        return SurfaceViewSpec(
            id=self._view_id,
            title=title,
            field_id=self._field_id,
            geometry_id=self._geometry_id,
            **kwargs,
        )

    def _panel_spec(self):
        from compneurovis.core.app_spec import PanelSpec

        return PanelSpec(
            id=self._panel_id,
            kind=PANEL_KIND_VIEW_3D,
            view_ids=(self._view_id,),
            operator_ids=tuple(self._operator_ids),
            camera_distance=self.camera_distance,
            camera_elevation=self.camera_elevation,
            camera_azimuth=self.camera_azimuth,
        )

    def _replace_message(self):
        values = self._values()
        x, y = self._coords(values)
        return update_message(
            FieldReplace(
                field_id=self._field_id,
                values=values,
                coords={self.y_dim: y, self.x_dim: x},
            )
        )


class SurfaceHandle(PanelHandle):
    __slots__ = ("_binding",)

    def __init__(self, binding: SurfaceBinding) -> None:
        super().__init__(binding._panel_id)
        # PanelHandle is a frozen slots dataclass, whose generated __setattr__
        # cannot be called from a subclass instance. Bypass it.
        object.__setattr__(self, "_binding", binding)

    @property
    def field_id(self) -> str:
        return self._binding._field_id

    @property
    def geometry_id(self) -> str:
        return self._binding._geometry_id

    @property
    def view_id(self) -> str:
        return self._binding._view_id


@dataclass
class GridSliceBinding:
    name: str
    surface: SurfaceBinding
    axis: Any
    position: Any
    line_kwargs: dict[str, Any] = field(default_factory=dict)
    overlay_kwargs: dict[str, Any] = field(default_factory=dict)
    _operator_id: str = field(init=False, default="")
    _view_id: str = field(init=False, default="")
    _panel_id: str = field(init=False, default="")

    def _register(self, index: int) -> None:
        slug = _slug(self.name)
        self._operator_id = f"grid_slice_{index}_{slug}"
        self._view_id = f"grid_slice_{index}_{slug}_plot"
        self._panel_id = f"grid-slice-panel-{index}-{slug}"
        self.surface._operator_ids.append(self._operator_id)

    def contribution(self, backend: Any = None) -> PanelContribution:
        del backend
        widget = self._line_widget()
        return PanelContribution(
            operators=(self._operator_spec(),),
            views=(widget.view_spec(),),
            panel=widget.panel_spec(),
        )

    def _operator_spec(self) -> GridSliceOperatorSpec:
        return GridSliceOperatorSpec(
            id=self._operator_id,
            field_id=self.surface._field_id,
            geometry_id=self.surface._geometry_id,
            axis_value_key=_binding_key(self.axis),
            position_value_key=_binding_key(self.position),
            **{key: bind(value) for key, value in self.overlay_kwargs.items()},
        )

    def _line_widget(self) -> LinePlotWidget:
        kwargs = {key: bind(value) for key, value in self.line_kwargs.items()}
        title = kwargs.pop("title", self.name)
        levels = kwargs.pop("levels", ())
        # A slice cuts one grid axis and plots along whichever survives, so the
        # x dim flips with the slice axis. None means "follow the sliced field".
        x_dim = kwargs.pop("x_dim", None)
        return LinePlotWidget(
            operator_id=self._operator_id,
            view_id=self._view_id,
            panel_id=self._panel_id,
            title=title,
            x_dim=x_dim,
            levels=levels,
            style=kwargs,
        )

    def _view_spec(self) -> LinePlotViewSpec:
        return self._line_widget().view_spec()

    def _panel_spec(self) -> PanelSpec:
        return self._line_widget().panel_spec()


class GridSliceHandle(PanelHandle):
    __slots__ = ("_binding",)

    def __init__(self, binding: GridSliceBinding) -> None:
        super().__init__(binding._panel_id)
        # See SurfaceHandle: PanelHandle's frozen __setattr__ rejects subclasses.
        object.__setattr__(self, "_binding", binding)

    @property
    def operator_id(self) -> str:
        return self._binding._operator_id


@dataclass
class DerivedValueBinding:
    name: str
    fn: Callable[[], Any]
    max_refresh_hz: float | None = 10.0
    initial: Any = None
    _last_eval_s: float = field(init=False, default=float("-inf"))

    def due(self, now: float) -> bool:
        interval = (1.0 / self.max_refresh_hz) if self.max_refresh_hz and self.max_refresh_hz > 0 else 0.0
        return (now - self._last_eval_s) >= interval

    def evaluate(self, now: float) -> Any:
        self._last_eval_s = now
        return self.fn()


class LineHandle(PanelHandle):
    """Panel handle for a line plot (from ``source.line``).

    Subclasses ``PanelHandle`` like every other widget handle, so both forms of
    ``line`` return the same type: ``read=`` (owns a sampled trace) and
    ``source=``/``field_id=`` (references a field another widget/backend
    declares). ``read=`` lines carry their trace binding and so also support
    ``sample()``; field-backed lines have no trace and leave it a no-op.
    """

    __slots__ = ("_binding", "_field_id")

    def __init__(
        self,
        panel_id: str,
        binding: TraceBinding | None = None,
        *,
        field_id: str | None = None,
    ) -> None:
        super().__init__(panel_id)
        # PanelHandle is a frozen slots dataclass; bypass its __setattr__.
        object.__setattr__(self, "_binding", binding)
        resolved = field_id if field_id is not None else (binding._field_id if binding is not None else None)
        object.__setattr__(self, "_field_id", resolved)

    @property
    def field_id(self) -> str | None:
        """The data field this line draws -- the target for ``ctx.clear(handle)``."""
        return self._field_id

    @property
    def name(self) -> str | None:
        return None if self._binding is None else self._binding.name

    def sample(self) -> None:
        """Sample this line's read-trace now, skipping the end-of-tick auto-sample.

        No-op for field-backed lines (``source=``/``field_id=``), which have no
        trace of their own to sample.
        """
        if self._binding is not None:
            self._binding._sample()


@dataclass(frozen=True, slots=True)
class BarHandle(PanelHandle):
    """Panel handle for a bar plot (from ``source.bar``)."""


@dataclass(frozen=True, slots=True)
class StateGraphHandle(PanelHandle):
    """Panel handle for a state graph (from ``source.state_graph``)."""


class ControlHandle:
    """User-facing reference to a registered control."""

    __slots__ = ("_binding",)

    def __init__(self, binding: ControlBinding) -> None:
        self._binding = binding

    @property
    def name(self) -> str:
        return self._binding.name

    @property
    def value_key(self) -> str:
        """The runtime binding key this control's value lives under (its id)."""
        return self._binding._control_id


class SliderHandle(ControlHandle):
    """Handle returned by ``source.slider(...)``."""


class NumberHandle(ControlHandle):
    """Handle returned by ``source.number(...)``."""


class DropdownHandle(ControlHandle):
    """Handle returned by ``source.dropdown(...)``."""


class CheckboxHandle(ControlHandle):
    """Handle returned by ``source.checkbox(...)``."""


class TextHandle(ControlHandle):
    """Handle returned by ``source.text(...)``."""


class XYPadHandle(ControlHandle):
    """Handle returned by ``source.xy_pad(...)``."""


class ActionHandle:
    """User-facing reference to a registered action."""

    __slots__ = ("_binding",)

    def __init__(self, binding: ActionBinding) -> None:
        self._binding = binding

    @property
    def name(self) -> str:
        return self._binding.name


def append_bindings_to_app_spec(
    app_spec: AppSpec | StartupData,
    *,
    panel_bindings: Sequence[Any] = (),
    controls: Sequence[ControlBinding] = (),
    actions: Sequence[ActionBinding] = (),
    backend: Any = None,
) -> AppSpec:
    """Merge widget contributions + controls/actions into an AppSpec.

    Every widget -- generic or backend -- is a ``PanelBinding`` exposing
    ``contribution(backend) -> PanelContribution``, merged by one uniform loop so
    no source special-cases a widget by kind. ``controls``/``actions`` are the
    source-declared interactions that share the controls panel. Widget-level
    controls are reserved for already-built low-level specs, not source-level
    convenience APIs.
    """
    from compneurovis.core.app_spec import PanelSpec

    if isinstance(app_spec, StartupData):
        app_spec = app_spec.app_spec()

    fields = dict(app_spec.data.fields)
    geometries = dict(app_spec.data.geometries)
    views = dict(app_spec.view_catalog.views)
    operators = dict(app_spec.view_catalog.operators)
    controls_by_id = dict(app_spec.interactions.controls)
    actions_by_id = dict(app_spec.interactions.actions)
    layouts = dict(app_spec.layout_catalog.layouts)
    layout = layouts[app_spec.layout_catalog.active]
    panels = list(layout.panels)
    panel_grid = list(layout.panel_grid)
    panel_ids = {panel.id for panel in panels}
    extra_control_ids: list[str] = []

    for widget in panel_bindings:
        contribution = widget.contribution(backend)
        for spec in contribution.fields:
            fields[spec.id] = spec
        for spec in contribution.geometries:
            geometries[spec.id] = spec
        for spec in contribution.views:
            views[spec.id] = spec
        for spec in contribution.operators:
            operators[spec.id] = spec
        for spec in contribution.controls:
            controls_by_id[spec.id] = spec
            if spec.id not in extra_control_ids:
                extra_control_ids.append(spec.id)
        panel = contribution.panel
        if panel is not None and panel.id not in panel_ids:
            panels.append(panel)
            panel_grid.append((panel.id,))
            panel_ids.add(panel.id)

    for control in controls:
        controls_by_id[control._control_id] = control._control_spec()
    for action in actions:
        actions_by_id[action._action_id] = action._action_spec()

    source_control_ids = tuple(control._control_id for control in controls)
    control_ids = tuple(dict.fromkeys((*extra_control_ids, *source_control_ids)))
    # Every action lives in the catalog (so key-only effects still resolve their
    # shortcuts), but only button-triggered ones get a panel entry.
    action_ids = tuple(action._action_id for action in actions if action.show_button)
    if control_ids or action_ids:
        controls_panel_index = next(
            (index for index, panel in enumerate(panels) if panel.kind == PANEL_KIND_CONTROLS),
            None,
        )
        if controls_panel_index is None:
            controls_panel = PanelSpec(
                id="controls-panel",
                kind=PANEL_KIND_CONTROLS,
                control_ids=control_ids,
                action_ids=action_ids,
            )
            panels.append(controls_panel)
            panel_grid.append((controls_panel.id,))
        else:
            panel = panels[controls_panel_index]
            panels[controls_panel_index] = replace(
                panel,
                control_ids=tuple(dict.fromkeys((*panel.control_ids, *control_ids))),
                action_ids=tuple(dict.fromkeys((*panel.action_ids, *action_ids))),
            )

    layouts[app_spec.layout_catalog.active] = LayoutSpec(
        title=layout.title,
        panels=tuple(panels),
        panel_grid=tuple(panel_grid),
    )
    return AppSpec(
        data=DataCatalog(fields=fields, geometries=geometries),
        view_catalog=ViewCatalog(views=views, operators=operators),
        interactions=InteractionCatalog(controls=controls_by_id, actions=actions_by_id),
        layout_catalog=LayoutCatalog(
            layouts=layouts,
            active=app_spec.layout_catalog.active,
        ),
        metadata=app_spec.metadata,
    )


class TraceSampler:
    """Trace sampler for sources that produce multiple samples per tick.

    Exposed to a source's step function as ``ctx.trace_sampler`` so it can pull a
    sample from every declared trace at whatever cadence it advances. Traces read
    arbitrary values, so this belongs with the trace bindings, not any backend.
    """

    def __init__(self, traces: list[TraceBinding]) -> None:
        self._traces = traces

    def sample(self) -> None:
        for trace in self._traces:
            trace._sample()

    def _begin_update(self) -> None:
        for trace in self._traces:
            trace._begin_frame()


def emit_trace_updates(backend: BackendBase, traces: list[TraceBinding], *, auto_sample: bool = True) -> None:
    for trace in traces:
        if auto_sample and not trace._sampled_this_frame:
            trace._sample()
        msg = trace._drain_message()
        if msg is not None:
            backend.emit_update(msg.payload)


__all__ = [
    "ActionBinding",
    "ActionHandle",
    "BarHandle",
    "ControlBinding",
    "ControlHandle",
    "XYPadHandle",
    "TextHandle",
    "CheckboxHandle",
    "DropdownHandle",
    "NumberHandle",
    "SliderHandle",
    "DerivedValueBinding",
    "GridSliceBinding",
    "GridSliceHandle",
    "FieldSource",
    "BarPlotWidget",
    "LineHandle",
    "MorphologyHandle",
    "MorphologyWidget",
    "LinePlotWidget",
    "PanelContribution",
    "PanelHandle",
    "SelectionRef",
    "SeriesReaders",
    "StartupData",
    "StateGraphHandle",
    "StateGraphWidget",

    "SurfaceBinding",
    "SurfaceHandle",
    "TraceBinding",
    "TraceSampler",
    "ValueRef",
    "append_bindings_to_app_spec",
    "bind",
    "emit_trace_updates",
]

