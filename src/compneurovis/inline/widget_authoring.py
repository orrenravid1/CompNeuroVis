"""Source-level widget declarations and their narrow authoring context."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Protocol, TYPE_CHECKING, TypeVar

import numpy as np

from compneurovis.inline._ids import slug
from compneurovis.core.app_spec import PANEL_KIND_EXTENSION, PanelSpec
from compneurovis.core.views import ExtensionViewSpec
from compneurovis.inline.data_bindings import SeriesReaders, TraceBinding
from compneurovis.inline.handles import (
    BarHandle,
    DataHandle,
    LineHandle,
    Network2DHandle,
    PanelHandle,
    bind,
)
from compneurovis.inline.widget_contributions import SpecWidget
from compneurovis.inline.widget_specs import BarPlotWidget, LinePlotWidget

if TYPE_CHECKING:
    from compneurovis.inline.sources import InlineSourceBase


HandleT = TypeVar("HandleT")
_MISSING = object()


class Widget(Protocol, Generic[HandleT]):
    """A reusable source-level declaration attachable with source.add()."""

    def attach(self, context: WidgetAuthoringContext) -> HandleT:
        """Declare this widget through the provided authoring context."""


@dataclass(frozen=True, slots=True)
class LineWidget:
    """Reusable declaration equivalent to source.line()."""

    name: str
    read: SeriesReaders | None = None
    source: DataHandle | None = None
    field_id: str | None = None
    x: Callable[[], float] | str | None = "time"
    by: str | None = None
    select: Mapping[str, Any] | None = None
    levels: Sequence[Any] = ()
    panel_id: str | None = None
    style: Mapping[str, Any] = field(default_factory=dict)

    def attach(self, context: WidgetAuthoringContext) -> LineHandle:
        return context._attach_line(self)


@dataclass(frozen=True, slots=True)
class BarWidget:
    """Reusable declaration equivalent to source.bar()."""

    name: str
    values: Any = None
    read: Callable[[], Any] | None = None
    source: DataHandle | None = None
    field_id: str | None = None
    series: Sequence[str] | None = None
    by: str | None = None
    unit: str | None = None
    levels: Sequence[Any] = ()
    panel_id: str | None = None
    style: Mapping[str, Any] = field(default_factory=dict)

    def attach(self, context: WidgetAuthoringContext) -> BarHandle:
        return context._attach_bar(self)


@dataclass(frozen=True, slots=True)
class Network2D:
    """A two-dimensional network with optional live node and edge values."""

    name: str
    nodes: Mapping[str, tuple[float, float]]
    edges: Sequence[tuple[str, str] | tuple[str, str, str]]
    node_values: Any = None
    node_read: Callable[[], Any] | None = None
    node_data: DataHandle | None = None
    edge_values: Any = None
    edge_read: Callable[[], Any] | None = None
    edge_data: DataHandle | None = None
    panel_id: str | None = None
    style: Mapping[str, Any] = field(default_factory=dict)

    def attach(self, context: WidgetAuthoringContext) -> Network2DHandle:
        node_names = tuple(str(name) for name in self.nodes)
        edges = tuple(
            (str(edge[0]), str(edge[1]), str(edge[2]) if len(edge) == 3 else f"edge_{index}")
            for index, edge in enumerate(self.edges)
        )
        edge_names = tuple(edge[2] for edge in edges)
        node_data = _network_data(
            context,
            f"{self.name} nodes",
            values=self.node_values,
            read=self.node_read,
            source=self.node_data,
            labels=node_names,
        )
        edge_data = _network_data(
            context,
            f"{self.name} edges",
            values=self.edge_values,
            read=self.edge_read,
            source=self.edge_data,
            labels=edge_names,
        )
        style = dict(self.style)
        title = style.pop("title", self.name)
        max_refresh_hz = style.pop("max_refresh_hz", None)
        panel = context.view(
            "network2d",
            self.name,
            inputs={"nodes": node_data, "edges": edge_data},
            properties={
                "node_positions": tuple(
                    (str(name), float(position[0]), float(position[1]))
                    for name, position in self.nodes.items()
                ),
                "edges": edges,
                **style,
            },
            title=title,
            panel_id=self.panel_id,
            max_refresh_hz=max_refresh_hz,
        )
        return Network2DHandle(panel.id)


class WidgetAuthoringContext:
    """Capabilities available while a widget is attached to a source."""

    __slots__ = ("__source",)

    def __init__(self, source: InlineSourceBase) -> None:
        self.__source = source

    def add(self, widget: Widget[HandleT]) -> HandleT:
        """Attach a widget declaration and return its handle."""
        attach = getattr(widget, "attach", None)
        if not callable(attach):
            raise TypeError(
                f"source.add() expects an object with attach(context), got {type(widget).__name__}"
            )
        return attach(self)

    def data(
        self,
        name: str,
        *,
        values: Any = _MISSING,
        read: Callable[[], Any] | None = None,
        source: DataHandle | None = None,
        labels: Sequence[str] | None = None,
        unit: str | None = None,
    ) -> DataHandle:
        """Declare or reuse data consumed by a widget."""
        if source is not None:
            if values is not _MISSING or read is not None:
                raise ValueError("data(...) accepts source=..., or values=/read=..., not both")
            return source
        if values is not _MISSING and read is not None:
            raise ValueError("data(...) accepts values=... or read=..., not both")
        if values is _MISSING and read is None:
            raise ValueError("data(...) requires values=..., read=..., or source=...")
        if values is _MISSING:
            if labels is None:
                raise ValueError("data(..., read=...) requires labels=(...)")
            initial_values: Any = np.zeros(len(labels), dtype=np.float32)
        else:
            initial_values = values
        if labels is None:
            size = np.asarray(initial_values).reshape(-1).size
            resolved_labels = tuple(str(index) for index in range(size))
        else:
            resolved_labels = tuple(str(label) for label in labels)
        binding = self.__source._declare_field(
            field_id=f"{slug(name)}_data",
            dim="item",
            labels=resolved_labels,
            values=initial_values,
            read=read,
            unit=unit,
        )
        self.__source._add_widget(
            field_builders=(lambda backend, _binding=binding: _binding.field_spec(),)
        )
        return DataHandle(
            _field_id=binding.field_id,
            _series_dim="item",
            _selectors={},
            _unit=unit,
        )

    def view(
        self,
        kind: str,
        name: str,
        *,
        inputs: Mapping[str, DataHandle] | None = None,
        properties: Mapping[str, Any] | None = None,
        title: Any = None,
        panel_id: str | None = None,
        max_refresh_hz: float | None = None,
    ) -> PanelHandle:
        """Declare one extension view without exposing AppSpec internals."""
        name_slug = slug(name)
        view_id = f"{name_slug}_{slug(kind)}"
        resolved_panel_id = panel_id or f"{name_slug}-panel"
        input_ids = {
            str(role): data._field_id
            for role, data in (inputs or {}).items()
        }
        self.__source._add_widget_binding(
            SpecWidget(
                views=(
                    ExtensionViewSpec(
                        id=view_id,
                        title=bind(name if title is None else title),
                        kind=kind,
                        inputs=input_ids,
                        properties=_bind_tree(properties or {}),
                        max_refresh_hz=max_refresh_hz,
                    ),
                ),
                panel=PanelSpec(
                    id=resolved_panel_id,
                    kind=PANEL_KIND_EXTENSION,
                    view_ids=(view_id,),
                ),
            )
        )
        return PanelHandle(resolved_panel_id)

    def line(
        self,
        name: str,
        *,
        read: SeriesReaders | None = None,
        source: DataHandle | None = None,
        field_id: str | None = None,
        x: Callable[[], float] | str | None = "time",
        by: str | None = None,
        select: Mapping[str, Any] | None = None,
        levels: Sequence[Any] = (),
        panel_id: str | None = None,
        **style: Any,
    ) -> LineHandle:
        """Compose a line plot into the current widget."""
        return self.add(
            LineWidget(
                name=name,
                read=read,
                source=source,
                field_id=field_id,
                x=x,
                by=by,
                select=select,
                levels=levels,
                panel_id=panel_id,
                style=style,
            )
        )

    def bar(
        self,
        name: str,
        *,
        values: Any = None,
        read: Callable[[], Any] | None = None,
        source: DataHandle | None = None,
        field_id: str | None = None,
        series: Sequence[str] | None = None,
        by: str | None = None,
        unit: str | None = None,
        levels: Sequence[Any] = (),
        panel_id: str | None = None,
        **style: Any,
    ) -> BarHandle:
        """Compose a bar plot into the current widget."""
        return self.add(
            BarWidget(
                name=name,
                values=values,
                read=read,
                source=source,
                field_id=field_id,
                series=series,
                by=by,
                unit=unit,
                levels=levels,
                panel_id=panel_id,
                style=style,
            )
        )

    def _attach_line(self, declaration: LineWidget) -> LineHandle:
        style = dict(declaration.style)
        if declaration.read is not None:
            binding = TraceBinding(
                name=declaration.name,
                read=declaration.read,
                x=declaration.x if callable(declaration.x) else None,
                **style,
            )
            self.__source._add_trace(binding)
            return LineHandle(binding._panel_id, binding)

        name_slug = slug(declaration.name)
        data_source = declaration.source
        resolved_field_id = declaration.field_id or (
            data_source._field_id if data_source is not None else None
        )
        if resolved_field_id is None:
            raise ValueError("line(...) requires read=..., source=..., or field_id=...")
        view_id = f"{name_slug}_plot"
        resolved_panel_id = declaration.panel_id or f"{name_slug}-panel"
        series_dim = declaration.by or (
            data_source._series_dim if data_source is not None else None
        )
        raw_selectors = (
            declaration.select
            if declaration.select is not None
            else (data_source._selectors if data_source is not None else {})
        )
        selectors = {dim: bind(value) for dim, value in raw_selectors.items()}
        if data_source is not None and data_source._unit is not None and "y_unit" not in style:
            style["y_unit"] = data_source._unit
        title = style.pop("title", declaration.name)
        self.__source._add_widget_binding(
            LinePlotWidget(
                field_id=resolved_field_id,
                view_id=view_id,
                panel_id=resolved_panel_id,
                title=title,
                x_dim=(
                    declaration.x
                    if isinstance(declaration.x, str) or declaration.x is None
                    else "time"
                ),
                series_dim=series_dim,
                selectors=selectors,
                levels=declaration.levels,
                style=style,
            )
        )
        return LineHandle(resolved_panel_id, field_id=resolved_field_id)

    def _attach_bar(self, declaration: BarWidget) -> BarHandle:
        style = dict(declaration.style)
        name_slug = slug(declaration.name)
        view_id = f"{name_slug}_bar"
        resolved_panel_id = declaration.panel_id or f"{name_slug}-panel"
        data_source = declaration.source
        category_dim = declaration.by or (
            data_source._series_dim if data_source is not None else None
        ) or "series"
        owns_data = declaration.values is not None or declaration.read is not None

        field_builders: tuple = ()
        unit = declaration.unit
        if owns_data:
            if data_source is not None or declaration.field_id is not None:
                raise ValueError("bar(...) takes values=/read=, or source=/field_id=, not both")
            binding = self.__source._declare_field(
                field_id=f"{name_slug}_field",
                dim=category_dim,
                labels=_category_labels(
                    declaration.series,
                    declaration.values,
                    declaration.name,
                ),
                values=declaration.values,
                read=declaration.read,
                unit=unit,
            )
            resolved_field_id = binding.field_id
            field_builders = (lambda backend, _binding=binding: _binding.field_spec(),)
        else:
            resolved_field_id = declaration.field_id or (
                data_source._field_id if data_source is not None else None
            )
            if resolved_field_id is None:
                raise ValueError(
                    "bar(...) requires values=..., read=..., source=..., or field_id=..."
                )
            if data_source is not None and data_source._unit is not None and unit is None:
                unit = data_source._unit
        if unit is not None and "y_unit" not in style:
            style["y_unit"] = unit
        title = style.pop("title", declaration.name)
        self.__source._add_widget_binding(
            BarPlotWidget(
                field_id=resolved_field_id,
                view_id=view_id,
                panel_id=resolved_panel_id,
                title=title,
                category_dim=category_dim,
                levels=declaration.levels,
                field_builders=field_builders,
                style=style,
            )
        )
        return BarHandle(resolved_panel_id)


def _category_labels(
    series: Sequence[str] | None,
    values: Any,
    name: str,
) -> tuple[str, ...]:
    if series is not None:
        return tuple(str(item) for item in series)
    if values is None:
        raise ValueError(f"bar({name!r}) with read=... requires series=(...) category labels")
    return tuple(str(index) for index in range(np.asarray(values).reshape(-1).size))


def _network_data(
    context: WidgetAuthoringContext,
    name: str,
    *,
    values: Any,
    read: Callable[[], Any] | None,
    source: DataHandle | None,
    labels: Sequence[str],
) -> DataHandle:
    if source is not None:
        return context.data(name, source=source)
    if read is not None:
        return context.data(name, read=read, labels=labels)
    initial = np.zeros(len(labels), dtype=np.float32) if values is None else values
    return context.data(name, values=initial, labels=labels)


def _bind_tree(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _bind_tree(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_bind_tree(item) for item in value)
    if isinstance(value, list):
        return [_bind_tree(item) for item in value]
    return bind(value)


__all__ = [
    "BarWidget",
    "LineWidget",
    "Network2D",
    "Widget",
    "WidgetAuthoringContext",
]
