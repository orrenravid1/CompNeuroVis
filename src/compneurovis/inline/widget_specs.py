"""Backend-independent builders for widget views and panels."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Sequence

from compneurovis.core.app_spec import (
    PANEL_KIND_BAR_PLOT,
    PANEL_KIND_LINE_PLOT,
    PANEL_KIND_VIEW_3D,
    PanelSpec,
)
from compneurovis.core.values import ValueBindingSpec
from compneurovis.core.views import (
    BarPlotViewSpec,
    LevelMarker,
    LinePlotViewSpec,
    MorphologyViewSpec,
)
from compneurovis.inline.handles import ControlHandle, ValueRef, bind, binding_key
from compneurovis.inline.widget_contributions import (
    FieldInput,
    WidgetContribution,
)


def _level_items(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(
        value,
        (str, bytes, LevelMarker, ValueBindingSpec, ControlHandle, ValueRef),
    ):
        return (value,)
    try:
        return tuple(value)
    except TypeError:
        return (value,)


def _to_level(item: Any, default_orientation: str) -> LevelMarker:
    if isinstance(item, LevelMarker):
        return item
    if isinstance(item, (ControlHandle, ValueRef)):
        return LevelMarker(
            value=ValueBindingSpec(binding_key(item)),
            orientation=default_orientation,
        )
    if isinstance(item, str):
        return LevelMarker(
            value=ValueBindingSpec(item),
            orientation=default_orientation,
        )
    if isinstance(item, ValueBindingSpec):
        return LevelMarker(value=item, orientation=default_orientation)
    return LevelMarker(value=float(item), orientation=default_orientation)


@dataclass
class LinePlotWidget:
    """Presentation for an already-declared field or operator."""

    view_id: str
    panel_id: str
    title: Any
    field_id: str | None = None
    operator_id: str | None = None
    x_dim: str | None = "time"
    series_dim: str | None = None
    selectors: Mapping[str, Any] = field(default_factory=dict)
    levels: Sequence[Any] = ()
    field_builders: tuple[FieldInput, ...] = ()
    panel_title: str | None = None
    style: Mapping[str, Any] = field(default_factory=dict)

    def contribution(self, backend: Any = None) -> WidgetContribution:
        return WidgetContribution(
            fields=tuple(
                item(backend) if callable(item) else item
                for item in self.field_builders
            ),
            views=(self.view_spec(),),
            panel=self.panel_spec(),
        )

    def view_spec(self) -> LinePlotViewSpec:
        kwargs = {key: bind(value) for key, value in self.style.items()}
        style_levels = kwargs.pop("levels", ())
        levels = tuple(
            _to_level(item, "horizontal")
            for item in (
                *_level_items(self.levels),
                *_level_items(style_levels),
            )
        )
        selectors = {
            dimension: bind(value)
            for dimension, value in self.selectors.items()
        }
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
    """Presentation for morphology geometry and optional scalar coloring."""

    view_id: str
    panel_id: str
    title: Any
    geometry_id: str | Callable[[Any], str]
    color_field_id: str | None = None
    entity_dim: str = "segment"
    sample_dim: str | None = None
    selectable: bool = True
    style: Mapping[str, Any] = field(default_factory=dict)

    def contribution(self, backend: Any = None) -> WidgetContribution:
        return WidgetContribution(
            views=(self.view_spec(backend),),
            panel=self.panel_spec(),
        )

    def view_spec(self, backend: Any = None) -> MorphologyViewSpec:
        geometry_id = (
            self.geometry_id(backend)
            if callable(self.geometry_id)
            else self.geometry_id
        )
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
        return PanelSpec(
            id=self.panel_id,
            kind=PANEL_KIND_VIEW_3D,
            view_ids=(self.view_id,),
        )


@dataclass
class BarPlotWidget:
    """Presentation for categorical scalar data."""

    field_id: str
    view_id: str
    panel_id: str
    title: Any
    category_dim: str | None = "series"
    levels: Sequence[Any] = ()
    field_builders: tuple[FieldInput, ...] = ()
    style: Mapping[str, Any] = field(default_factory=dict)

    def contribution(self, backend: Any = None) -> WidgetContribution:
        return WidgetContribution(
            fields=tuple(
                item(backend) if callable(item) else item
                for item in self.field_builders
            ),
            views=(self.view_spec(),),
            panel=self.panel_spec(),
        )

    def view_spec(self) -> BarPlotViewSpec:
        kwargs = {key: bind(value) for key, value in self.style.items()}
        style_levels = kwargs.pop("levels", ())
        levels = tuple(
            _to_level(item, "vertical")
            for item in (
                *_level_items(self.levels),
                *_level_items(style_levels),
            )
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
        return PanelSpec(
            id=self.panel_id,
            kind=PANEL_KIND_BAR_PLOT,
            view_ids=(self.view_id,),
        )

__all__ = [
    "BarPlotWidget",
    "LinePlotWidget",
    "MorphologyWidget",
]
