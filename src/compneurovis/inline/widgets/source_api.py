"""Shared ``source.*`` widget facade inherited by every source type.

This is the intentional local customization point for source-level widgets.
Add a thin method here that constructs a widget and passes it to ``add()``;
generic, NEURON, Jaxley, and future sources inherit it automatically.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Callable, TypeVar

from compneurovis.core.geometry import MorphologyGeometrySpec
from compneurovis.inline.refs import (
    BarRef,
    DataRef,
    GridSliceRef,
    LineRef,
    MorphologyRef,
    Network2DRef,
    SurfaceRef,
)
from compneurovis.inline.widgets.api import Widget, WidgetAuthoringContext
from compneurovis.inline.widgets.bar import Bar
from compneurovis.inline.widgets.grid_slice import GridSlice
from compneurovis.inline.widgets.line import Line, SeriesReaders
from compneurovis.inline.widgets.morphology import Morphology
from compneurovis.inline.widgets.network2d import Network2D
from compneurovis.inline.widgets.surface import Surface


HandleT = TypeVar("HandleT")


class SourceWidgetAPI:
    """Backend-neutral widget methods shared by every inline source."""

    def add(self, widget: Widget[HandleT]) -> HandleT:
        """Attach a reusable widget declaration to this source."""
        return WidgetAuthoringContext(self).add(widget)

    def line(
        self,
        name: str,
        *,
        read: SeriesReaders | None = None,
        source: DataRef | None = None,
        x: Callable[[], float] | str | None = "time",
        by: str | None = None,
        select: Mapping[str, Any] | None = None,
        levels: Sequence[Any] = (),
        panel_id: str | None = None,
        **style: Any,
    ) -> LineRef:
        """Add a line plot backed by readers or any source data handle."""
        return self.add(
            Line(
                name=name,
                read=read,
                source=source,
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
        source: DataRef | None = None,
        series: Sequence[str] | None = None,
        by: str | None = None,
        unit: str | None = None,
        levels: Sequence[Any] = (),
        panel_id: str | None = None,
        **style: Any,
    ) -> BarRef:
        """Add a bar plot backed by values, a reader, or a data handle."""
        return self.add(
            Bar(
                name=name,
                values=values,
                read=read,
                source=source,
                series=series,
                by=by,
                unit=unit,
                levels=levels,
                panel_id=panel_id,
                style=style,
            )
        )

    def network2d(
        self,
        name: str,
        *,
        nodes: Mapping[str, tuple[float, float]],
        edges: Sequence[tuple[str, str] | tuple[str, str, str]],
        node_values: Any = None,
        node_read: Callable[[], Any] | None = None,
        node_data: DataRef | None = None,
        edge_values: Any = None,
        edge_read: Callable[[], Any] | None = None,
        edge_data: DataRef | None = None,
        panel_id: str | None = None,
        **style: Any,
    ) -> Network2DRef:
        """Add a two-dimensional network panel."""
        return self.add(
            Network2D(
                name=name,
                nodes=nodes,
                edges=edges,
                node_values=node_values,
                node_read=node_read,
                node_data=node_data,
                edge_values=edge_values,
                edge_read=edge_read,
                edge_data=edge_data,
                panel_id=panel_id,
                style=style,
            )
        )

    def morphology(
        self,
        geometry: MorphologyGeometrySpec,
        *,
        name: str = "Morphology",
        values: Any = None,
        read: Callable[[], Any] | None = None,
        unit: str | None = None,
        color_limits: tuple[float, float] | None = None,
        color_map: str = "scalar",
        color_norm: str = "auto",
        background_color: Any = "white",
        max_refresh_hz: float | None = None,
        selected: Any = None,
        selectable: bool = True,
        select_multiple: bool = False,
        panel: bool = True,
    ) -> MorphologyRef:
        """Add a custom morphology panel with optional live entity values."""
        return self.add(
            Morphology(
                geometry=geometry,
                name=name,
                values=values,
                read=read,
                unit=unit,
                color_limits=color_limits,
                color_map=color_map,
                color_norm=color_norm,
                background_color=background_color,
                max_refresh_hz=max_refresh_hz,
                selected=selected,
                selectable=selectable,
                select_multiple=select_multiple,
                panel=panel,
            )
        )

    def surface(
        self,
        name: str,
        *,
        values: Any = None,
        read: Callable[[], Any] | None = None,
        x: Any | None = None,
        y: Any | None = None,
        x_dim: str = "x",
        y_dim: str = "y",
        unit: str | None = None,
        camera_distance: float | None = 30.0,
        camera_elevation: float = 30.0,
        camera_azimuth: float = 30.0,
        **style: Any,
    ) -> SurfaceRef:
        """Add a static or live two-dimensional field as a 3-D surface."""
        return self.add(
            Surface(
                name=name,
                values=values,
                read=read,
                x=x,
                y=y,
                x_dim=x_dim,
                y_dim=y_dim,
                unit=unit,
                camera_distance=camera_distance,
                camera_elevation=camera_elevation,
                camera_azimuth=camera_azimuth,
                style=style,
            )
        )

    def grid_slice(
        self,
        name: str,
        *,
        surface: SurfaceRef,
        axis: Any,
        position: Any,
        overlay: dict[str, Any] | None = None,
        **style: Any,
    ) -> GridSliceRef:
        """Add a line plot showing one cross-section of a surface."""
        return self.add(
            GridSlice(
                name=name,
                surface=surface,
                axis=axis,
                position=position,
                overlay=overlay,
                style=style,
            )
        )


__all__ = ["SourceWidgetAPI"]
