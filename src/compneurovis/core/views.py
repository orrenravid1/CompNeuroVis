from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from compneurovis.core._immutability import FrozenDict
from compneurovis.core.specs import IdentifiedSpec

ValueOrBinding = Any
SelectorValue = Any


@dataclass(frozen=True, slots=True)
class ViewSpec(IdentifiedSpec):
    title: ValueOrBinding = ""


@dataclass(frozen=True, slots=True)
class MorphologyViewSpec(ViewSpec):
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
    tick_label_size: ValueOrBinding = 12.0
    axis_label_size: ValueOrBinding = 16.0
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
    field_id: str = ""
    operator_id: str | None = None
    x_dim: str | None = None
    series_dim: str | None = None
    selectors: Mapping[str, SelectorValue] = field(default_factory=FrozenDict)
    x_label: str = "x"
    y_label: str = "y"
    x_unit: str = ""
    y_unit: str = ""
    pen: ValueOrBinding = "k"
    background_color: ValueOrBinding = "w"
    show_legend: bool = True
    series_colors: Mapping[str, ValueOrBinding] = field(default_factory=FrozenDict)
    series_palette: tuple[ValueOrBinding, ...] = ()
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
        object.__setattr__(self, "series_colors", FrozenDict(self.series_colors))
        object.__setattr__(self, "series_palette", tuple(self.series_palette))
        object.__setattr__(self, "levels", tuple(self.levels))


@dataclass(frozen=True, slots=True)
class BarPlotViewSpec(ViewSpec):
    """Live bar chart — one bar per category (the coord labels of ``category_dim``)."""

    field_id: str = ""
    category_dim: str | None = None
    x_label: str = ""
    y_label: str = "y"
    y_unit: str = ""
    bar_color: ValueOrBinding = "#1f77b4"
    series_colors: Mapping[str, ValueOrBinding] = field(default_factory=FrozenDict)
    background_color: ValueOrBinding = "w"
    show_legend: bool = False
    y_min: float | None = None
    y_max: float | None = None
    max_refresh_hz: float | None = None
    levels: tuple[LevelMarker, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "series_colors", FrozenDict(self.series_colors))
        object.__setattr__(self, "levels", tuple(self.levels))


@dataclass(frozen=True, slots=True)
class StateGraphViewSpec(ViewSpec):
    """Static directed graph with live-colored nodes and edges.

    node_positions: each entry is (state_name, x, y) in normalized [0,1] canvas space.
    edges: each entry is (source_state, target_state, edge_id).
    node_field_id: Field with dims=("state",); values are current state occupancies.
    edge_field_id: Field with dims=("edge",); values are net fluxes or rates.
    """
    node_field_id: str = ""
    edge_field_id: str = ""
    node_positions: tuple[tuple[str, float, float], ...] = ()
    edges: tuple[tuple[str, str, str], ...] = ()
    node_color_map: str = "fire"
    edge_color_map: str = "bwr"
    node_color_limits: tuple[float, float] = (0.0, 1.0)
    edge_color_limits: tuple[float, float] = (-0.1, 0.1)
    node_size: float = 20.0
    background_color: Any = "white"
    max_refresh_hz: float | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_positions", tuple(tuple(item) for item in self.node_positions))
        object.__setattr__(self, "edges", tuple(tuple(item) for item in self.edges))
        object.__setattr__(self, "node_color_limits", tuple(self.node_color_limits))
        object.__setattr__(self, "edge_color_limits", tuple(self.edge_color_limits))
