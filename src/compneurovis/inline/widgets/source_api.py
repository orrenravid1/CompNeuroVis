"""Shared ``source.*`` widget facade inherited by every source type.

This is the intentional local customization point for source-level widgets.
Add a thin method here that constructs a widget and passes it to ``add()``;
generic, NEURON, Jaxley, and future sources inherit it automatically.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Callable, TypeVar

from compneurovis.inline.refs import (
    BarRef,
    DataRef,
    LineRef,
    MorphologyRef,
    Network2DRef,
    PanelRef,
    SurfaceRef,
)
from compneurovis.inline.widgets.api import Widget, WidgetAuthoringContext
from compneurovis.components.bar.authoring import Bar
from compneurovis.components.grid_slice.authoring import GridSlice
from compneurovis.components.level_marker.authoring import LevelMarker
from compneurovis.components.line.authoring import Line, SeriesReaders
from compneurovis.components.morphology.authoring import Morphology
from compneurovis.geometries.morphology import MorphologyGeometry
from compneurovis.components.network2d.authoring import Network2D
from compneurovis.components.surface.authoring import Surface
from compneurovis.inline.widget_registry import (
    _reserve_widget_names,
    registered_widgets,
    widget_factory,
)


RefT = TypeVar("RefT")

class SourceWidgetAPI:
    """The source-level widget surface -- every ``source.<widget>(...)`` method.

    Backend-neutral and shared by every inline source (generic, NEURON, Jaxley).
    **One funnel:** every method here, and every ``register_widget`` entry, ends
    in ``self.add(SomeWidget(...))``. A widget reaches it two ways:

    * **Typed, first-class -- the contributor extension point.** Add a thin proxy
      method here next to ``line``/``bar``/``surface``: a few lines that build the
      widget from typed arguments and ``return self.add(...)``. It is statically
      checked and inherited by every source. This is *the* place to make a widget
      a built-in -- a sincere contributor adds one method, nothing else.
    * **Dynamic, no library edit -- ``register_widget`` (public registry).** Any widget can
      be exposed as ``source.<name>(...)`` at runtime, dispatched through the same
      ``add``. This is the seamless path for a widget a user (or an agent) drops
      in without touching the library. It is deliberately *not* statically typed:
      a method registered at runtime is invisible to type checkers -- that is a
      property of static analysis, not a gap here.

    Either way, ``source.add(MyWidget(...))`` is always available and fully typed
    via ``Widget[Ref]`` for an author who wants typing without a named method.
    """

    def add(self, widget: Widget[RefT]) -> RefT:
        """Add a reusable widget to this source, returning its ref."""
        if not isinstance(widget, Widget):
            raise TypeError(
                f"source.add() expects a Widget, got {type(widget).__name__}"
            )
        return widget.declare(WidgetAuthoringContext(self))

    def __getattr__(self, name: str):
        # Named authoring sugar for registered widgets: ``source.<name>(...)`` is
        # ``source.add(factory(...))``. Python only calls __getattr__ when normal
        # lookup fails, so built-in methods (line/bar/...) and real attributes
        # always take precedence; unknown names still raise AttributeError.
        if name.startswith("_"):
            raise AttributeError(name)
        factory = widget_factory(name)
        if factory is None:
            from compneurovis.inline.control_registry import (
                control_factory,
                registered_controls,
            )

            if name not in registered_controls():
                raise AttributeError(
                    f"{type(self).__name__!r} object has no attribute {name!r}"
                )

            def build_control(*args: Any, **kwargs: Any) -> Any:
                return self._invoke_control_factory(
                    "controls-panel", name, *args, **kwargs
                )

            registered_factory = control_factory(name)
            build_control.__name__ = name
            build_control.__qualname__ = f"source.{name}"
            build_control.__doc__ = getattr(registered_factory, "__doc__", None)
            return build_control

        def build(*args: Any, **kwargs: Any) -> Any:
            return self.add(factory(*args, **kwargs))

        build.__name__ = name
        build.__qualname__ = f"source.{name}"
        build.__doc__ = getattr(factory, "__doc__", None)
        return build

    def __dir__(self):
        # Surface registered widget names so ``dir(source)`` / REPL completion
        # find them despite the dynamic ``__getattr__`` dispatch.
        from compneurovis.inline.control_registry import registered_controls

        return sorted(
            set(super().__dir__())
            | set(registered_widgets())
            | set(registered_controls())
        )

    def line(
        self,
        name: str,
        *,
        read: SeriesReaders | None = None,
        source: DataRef | None = None,
        x: Callable[[], float] | str | None = "time",
        by: str | None = None,
        select: Mapping[str, Any] | None = None,
        panel_id: str | None = None,
        **style: Any,
    ) -> LineRef:
        """Add a line plot backed by readers or any source data reference."""
        return self.add(
            Line(
                name=name,
                read=read,
                source=source,
                x=x,
                by=by,
                select=select,
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
        panel_id: str | None = None,
        **style: Any,
    ) -> BarRef:
        """Add a bar plot backed by values, a reader, or a data reference."""
        return self.add(
            Bar(
                name=name,
                values=values,
                read=read,
                source=source,
                series=series,
                by=by,
                unit=unit,
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
        geometry: MorphologyGeometry,
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
    ) -> DataRef:
        """Cut a cross-section through a surface.

        Draws the slice overlay on the surface and returns the sliced profile as
        a ``DataRef`` -- plain data. Plot it by composing a consumer, e.g.
        ``source.line("Profile", source=slice, x=None)``.
        """
        return self.add(
            GridSlice(
                name=name,
                surface=surface,
                axis=axis,
                position=position,
                overlay=overlay,
            )
        )

    def level_marker(
        self,
        target: PanelRef,
        value: Any,
        *,
        orientation: str = "horizontal",
        color: Any = "#d62728",
        width: float = 2.0,
        label: str = "",
    ) -> PanelRef:
        """Add an independently owned reference line to a Plot2D panel."""
        return self.add(
            LevelMarker(
                target=target,
                value=value,
                orientation=orientation,
                color=color,
                width=width,
                label=label,
            )
        )

_reserve_widget_names(
    name for name in vars(SourceWidgetAPI) if not name.startswith("_")
)


__all__ = ["SourceWidgetAPI"]
