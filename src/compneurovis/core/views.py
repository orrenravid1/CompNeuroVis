from __future__ import annotations

from collections.abc import Mapping as _AbcMapping
from dataclasses import dataclass, field
from typing import Any, ClassVar, Mapping

from compneurovis.core._immutability import FrozenDict
from compneurovis.core.specs import (
    PANEL_KIND_BAR_PLOT,
    PANEL_KIND_EXTENSION,
    PANEL_KIND_LINE_PLOT,
    PANEL_KIND_VIEW_3D,
    IdentifiedSpec,
)

ValueOrBinding = Any
SelectorValue = Any

# Per-series appearance (colors / linestyles / linewidths) is matplotlib-shaped:
# a ``{label: value}`` mapping (pandas ``.plot(color={...})`` style) or a plain
# sequence cycled by series index (matplotlib ``LineCollection`` style).
SeriesStyle = Any


def _freeze_series_style(value: Any) -> Any:
    """Normalize a per-series style to an immutable mapping or tuple."""
    if isinstance(value, _AbcMapping):
        return FrozenDict(value)
    return tuple(value)


@dataclass(frozen=True, slots=True)
class ViewSpec(IdentifiedSpec):
    title: ValueOrBinding = ""


@dataclass(frozen=True, slots=True)
class ExtensionViewSpec(ViewSpec):
    """Frontend-neutral declaration for an installed view extension.

    ``kind`` selects a frontend renderer. ``inputs`` gives that renderer named
    data dependencies, while ``properties`` contains immutable presentation
    configuration and runtime value bindings.
    """

    kind: str = ""
    inputs: Mapping[str, str] = field(default_factory=FrozenDict)
    properties: Mapping[str, Any] = field(default_factory=FrozenDict)
    max_refresh_hz: float | None = None
    # The panel category the author places this view in — declared, not inferred.
    panel_kind: str = PANEL_KIND_EXTENSION

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValueError("ExtensionViewSpec.kind cannot be empty")
        object.__setattr__(self, "inputs", FrozenDict(self.inputs))
        object.__setattr__(self, "properties", FrozenDict(self.properties))


@dataclass(frozen=True, slots=True)
class MorphologyViewSpec(ViewSpec):
    panel_kind: ClassVar[str] = PANEL_KIND_VIEW_3D
    kind: ClassVar[str] = "morphology"
    geometry_id: str = "morphology"
    color_field_id: str | None = None
    entity_dim: str = "segment"
    sample_dim: str | None = "time"
    selectable: bool = True
    color_map: str = "scalar"
    color_limits: ValueOrBinding = None
    color_norm: str = "auto"
    background_color: ValueOrBinding = "white"
    max_refresh_hz: float | None = None


@dataclass(frozen=True, slots=True)
class SurfaceViewSpec(ViewSpec):
    panel_kind: ClassVar[str] = PANEL_KIND_VIEW_3D
    kind: ClassVar[str] = "surface"
    field_id: str = ""
    geometry_id: str | None = None
    color_map: ValueOrBinding = "bwr"
    color_limits: ValueOrBinding = None
    color_by: ValueOrBinding = "height"
    surface_color: ValueOrBinding = (0.5, 0.6, 0.8, 1.0)
    surface_shading: ValueOrBinding = "unlit"
    surface_alpha: ValueOrBinding = 1.0
    background_color: ValueOrBinding = "white"
    render_axes: ValueOrBinding = False
    axes_in_middle: ValueOrBinding = True
    tick_count: ValueOrBinding = 5
    tick_length_scale: ValueOrBinding = 1.0
    tick_label_size: ValueOrBinding = 48.0
    axis_label_size: ValueOrBinding = 64.0
    axis_color: ValueOrBinding = "black"
    text_color: ValueOrBinding = "black"
    axis_alpha: ValueOrBinding = 1.0
    axis_labels: tuple[str, str, str] | None = None
    max_refresh_hz: float | None = None

    def __post_init__(self) -> None:
        if self.axis_labels is not None:
            object.__setattr__(self, "axis_labels", tuple(self.axis_labels))


@dataclass(frozen=True, slots=True)
class LevelMarker:
    """A reference line on a 2D plot, positioned by a value or binding.

    ``orientation="horizontal"`` draws y = value (e.g. a threshold on a trace);
    ``"vertical"`` draws x = value. ``value`` may be a number or a ValueBindingSpec
    so the line tracks a control/derived value live.
    """

    value: ValueOrBinding
    orientation: str = "horizontal"
    color: ValueOrBinding = "#d62728"
    width: float = 2.0
    label: str = ""


@dataclass(frozen=True, slots=True)
class LinePlotViewSpec(ViewSpec):
    panel_kind: ClassVar[str] = PANEL_KIND_LINE_PLOT
    kind: ClassVar[str] = "line_plot"
    field_id: str = ""
    operator_id: str | None = None
    x_dim: str | None = None
    series_dim: str | None = None
    selectors: Mapping[str, SelectorValue] = field(default_factory=FrozenDict)
    x_label: str = "x"
    y_label: str = "y"
    x_unit: str = ""
    y_unit: str = ""
    # matplotlib-style appearance. Singular props (``color``/``linestyle``/
    # ``linewidth``) are the default for the sole line, or for every series. The
    # plurals override per series: a ``{label: value}`` map, or a sequence cycled
    # by series index. ``linestyle`` takes matplotlib strings: "-", "--", "-.", ":".
    color: ValueOrBinding = "k"
    background_color: ValueOrBinding = "w"
    show_legend: bool = True
    colors: SeriesStyle = field(default_factory=FrozenDict)
    linestyle: ValueOrBinding = "-"
    linestyles: SeriesStyle = field(default_factory=FrozenDict)
    linewidth: ValueOrBinding = 2.0
    linewidths: SeriesStyle = field(default_factory=FrozenDict)
    rolling_window: float | None = None
    trim_to_rolling_window: bool = False
    max_refresh_hz: float | None = None
    y_min: float | None = None
    y_max: float | None = None
    x_major_tick_spacing: float | None = None
    x_minor_tick_spacing: float | None = None
    levels: tuple[LevelMarker, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "selectors", FrozenDict(self.selectors))
        object.__setattr__(self, "colors", _freeze_series_style(self.colors))
        object.__setattr__(self, "linestyles", _freeze_series_style(self.linestyles))
        object.__setattr__(self, "linewidths", _freeze_series_style(self.linewidths))
        object.__setattr__(self, "levels", tuple(self.levels))


@dataclass(frozen=True, slots=True)
class BarPlotViewSpec(ViewSpec):
    """Live bar chart — one bar per category (the coord labels of ``category_dim``)."""

    panel_kind: ClassVar[str] = PANEL_KIND_BAR_PLOT
    kind: ClassVar[str] = "bar_plot"
    field_id: str = ""
    category_dim: str | None = None
    x_label: str = ""
    y_label: str = "y"
    y_unit: str = ""
    color: ValueOrBinding = "#1f77b4"
    colors: SeriesStyle = field(default_factory=FrozenDict)
    background_color: ValueOrBinding = "w"
    show_legend: bool = False
    y_min: float | None = None
    y_max: float | None = None
    max_refresh_hz: float | None = None
    levels: tuple[LevelMarker, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "colors", _freeze_series_style(self.colors))
        object.__setattr__(self, "levels", tuple(self.levels))


@dataclass(frozen=True, slots=True)
class StateGraphViewSpec(ViewSpec):
    """Frontend render-config for a live-colored node/edge graph.

    Not an authored view: it is built internally by ``Network2DHostPanel`` to
    drive ``StateGraphPanel``. ``Network2D`` (an extension widget) is the graph
    authoring surface; this carries no ``panel_kind``/``kind``.

    node_positions: each entry is (state_name, x, y) in normalized [0,1] canvas space.
    edges: each entry is (source_state, target_state, edge_id).
    node_field_id: Field with dims=("state",); values are current state occupancies.
    edge_field_id: Field with dims=("edge",); values are net fluxes or rates.
    """
    node_field_id: str = ""
    edge_field_id: str = ""
    node_positions: tuple[tuple[str, float, float], ...] = ()
    edges: tuple[tuple[str, str, str], ...] = ()
    node_color_map: ValueOrBinding = "fire"
    edge_color_map: ValueOrBinding = "bwr"
    node_color_limits: tuple[float, float] = (0.0, 1.0)
    edge_color_limits: tuple[float, float] = (-0.1, 0.1)
    node_size: ValueOrBinding = 20.0
    edge_width: ValueOrBinding = 4.0
    arrow_size: ValueOrBinding = 12.0
    label_size: ValueOrBinding = 10.0
    # Nudge the node labels off the node centre, in pixels (+x right, +y up).
    label_offset_x: ValueOrBinding = 0.0
    label_offset_y: ValueOrBinding = 0.0
    background_color: ValueOrBinding = "white"
    max_refresh_hz: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_positions", tuple(tuple(item) for item in self.node_positions))
        object.__setattr__(self, "edges", tuple(tuple(item) for item in self.edges))
        object.__setattr__(self, "node_color_limits", tuple(self.node_color_limits))
        object.__setattr__(self, "edge_color_limits", tuple(self.edge_color_limits))
