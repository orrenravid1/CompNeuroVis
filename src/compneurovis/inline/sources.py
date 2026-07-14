"""Authoring-layer source adapters for inline mode."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import replace
from typing import Any, Callable

import numpy as np

from compneurovis.backends.base import BackendBase
from compneurovis.core.app_spec import (
    AppSpec,
    DataCatalog,
    InteractionCatalog,
    LayoutCatalog,
    LayoutSpec,
    ViewCatalog,
)
from compneurovis.core.controls import (
    BoolValueSpec,
    ChoiceValueSpec,
    ControlPresentationSpec,
    ControlValueSpec,
    ScalarValueSpec,
    TextValueSpec,
    XYValueSpec,
)
from compneurovis.core.geometry import MorphologyGeometrySpec
from compneurovis.backends.interaction import (
    BackendInteractionContext,
    SELECTED_ENTITY_ID_KEY,
    SELECTED_ENTITY_IDS_KEY,
    _selection_to_internal,
)
from compneurovis.core.messages import InvokeAction, MessagePayload, Reset
from compneurovis.inline.backend import InlineBackend
from compneurovis.inline.bindings import (
    ActionBinding,
    ActionHandle,
    ArrayFieldBinding,
    BarHandle,
    BarPlotWidget,
    ControlBinding,
    ControlHandle,
    XYPadHandle,
    TextHandle,
    SliderHandle,
    NumberHandle,
    DropdownHandle,
    CheckboxHandle,
    DerivedValueBinding,
    FieldSource,
    GridSliceBinding,
    GridSliceHandle,
    LineHandle,
    LinePlotWidget,
    MorphologyHandle,
    MorphologyWidget,
    PanelHandle,
    SelectionRef,
    SeriesReaders,
    SpecWidget,
    StateGraphHandle,
    StateGraphWidget,
    SurfaceBinding,
    SurfaceHandle,
    TraceBinding,
    ValueRef,
    _slug,
    append_bindings_to_app_spec,
    bind,
)

_MISSING = object()


class RemoteActorRef:
    """Reference to an actor hosted outside the current Python source."""

    def __init__(
        self,
        actor_id: str,
        *,
        send: Callable[[MessagePayload], None] | None = None,
    ) -> None:
        self.actor_id = actor_id
        self._send = send

    def command(self, command: MessagePayload) -> None:
        if self._send is not None:
            self._send(command)
            return
        raise NotImplementedError(
            "RemoteActorRef without a send callback requires multi-actor RunSpec "
            "lowering. It cannot be hidden behind a composed backend."
        )


    def invoke_action(self, action_id: str, payload: dict[str, Any] | None = None) -> None:
        self.command(InvokeAction(action_id, payload or {}))

    def reset(self) -> None:
        self.command(Reset())


def _category_labels(series: Sequence[str] | None, values: Any, name: str) -> tuple[str, ...]:
    if series is not None:
        return tuple(str(item) for item in series)
    if values is None:
        raise ValueError(f"bar({name!r}) with read=... requires series=(...) category labels")
    return tuple(str(index) for index in range(np.asarray(values).reshape(-1).size))


class InlineSourceBase:
    """Shared high-level authoring API for all source types.

    Sources begin with no panels. Calls such as `line()`,
    `morphology()`, and `surface()` opt views into the app; typed
    control and action methods opt interactions in. Obtain a concrete source
    from `cnv.source()` or a simulator namespace.
    """

    def __init__(self, *, title: str = "CompNeuroVis") -> None:
        self.title = title
        self._app_title: str | None = None
        self._traces: list[TraceBinding] = []
        self._widgets: list[Any] = []
        self._panel_bindings: list[Any] = []
        self._controls: list[ControlBinding] = []
        self._actions: list[ActionBinding] = []
        self._surfaces: list[SurfaceBinding] = []
        self._fields: list[ArrayFieldBinding] = []
        self._geometries: list[MorphologyGeometrySpec] = []
        self._selection_modes: dict[str, bool] = {}
        self._grid_slices: list[GridSliceBinding] = []
        self._derived_values: list[DerivedValueBinding] = []
        self._initial_values: list[tuple[str, Any]] = []
        self._panel_grid: tuple[tuple[str, ...], ...] | None = None
        self._handle = None
        from compneurovis.inline import _register_current_source
        _register_current_source(self)

    def line(
        self,
        name: str,
        *,
        read: SeriesReaders | None = None,
        source: FieldSource | None = None,
        field_id: str | None = None,
        x: Callable[[], float] | str | None = "time",
        by: str | None = None,
        select: Mapping[str, Any] | None = None,
        levels: Sequence[Any] = (),
        panel_id: str | None = None,
        **style: Any,
    ) -> LineHandle:
        """Add a line-plot panel.

        Args:
            name: User-facing plot name and default panel title.
            read: No-argument reader, or a mapping of series labels to readers,
                sampled after each source step.
            source: Data source returned by an operation such as
                `record()`, `record_refs()`, or `derive()`.
            field_id: Advanced identifier for data already declared by a
                backend. Prefer `source` in normal authoring code.
            x: For `read`, a callable returning the x value. For existing
                data, the dimension to use as x. `None` uses sample order.
            by: Dimension whose coordinates become separate plotted series.
            select: Dimension selectors. Values may be literals, controls, or
                values returned by `create_value()`.
            levels: Horizontal or vertical reference levels. Numeric values,
                controls, value references, and `LevelMarker` objects work.
            panel_id: Explicit panel identifier for advanced layout integration.
            **style: Plot styling such as `title`, `x_label`, `y_label`,
                `x_unit`, `y_unit`, `y_min`, `y_max`, `color`,
                `colors`, `linestyle`, `linewidth`, `show_legend`,
                `rolling_window`, `max_samples`, and `max_refresh_hz`.

        Returns:
            A handle accepted by `cnv.layout()` and `ctx.clear()`.

        `read` owns and samples a new trace. `source` reuses an optimized
        producer supplied by a simulator backend or another source operation.
        """
        if read is not None:
            binding = TraceBinding(name=name, read=read, x=x if callable(x) else None, **style)
            self._add_trace(binding)
            return LineHandle(binding._panel_id, binding)

        slug = _slug(name)
        resolved_field_id = field_id or (source.field_id if source is not None else None)
        if resolved_field_id is None:
            raise ValueError("line(...) requires read=..., source=..., or field_id=...")
        view_id = f"{slug}_plot"
        resolved_panel_id = panel_id or f"{slug}-panel"
        series_dim = by or (source.series_dim if source is not None else None)
        raw_selectors = select if select is not None else (source.selectors if source is not None else {})
        selectors = {dim: bind(value) for dim, value in raw_selectors.items()}
        if source is not None and source.unit is not None and "y_unit" not in style:
            style = {**style, "y_unit": source.unit}
        title = style.pop("title", name)
        self._widgets.append(
            LinePlotWidget(
                field_id=resolved_field_id,
                view_id=view_id,
                panel_id=resolved_panel_id,
                title=title,
                x_dim=x if isinstance(x, str) or x is None else "time",
                series_dim=series_dim,
                selectors=selectors,
                levels=levels,
                style=style,
            )
        )
        return LineHandle(resolved_panel_id, field_id=resolved_field_id)

    def bar(
        self,
        name: str,
        *,
        values: Any = None,
        read: Callable[[], Any] | None = None,
        source: FieldSource | None = None,
        field_id: str | None = None,
        series: Sequence[str] | None = None,
        by: str | None = None,
        unit: str | None = None,
        levels: Sequence[Any] = (),
        panel_id: str | None = None,
        **style: Any,
    ) -> BarHandle:
        """Add a bar-plot panel with one bar per category.

        Args:
            name: User-facing plot name and default panel title.
            values: Static one-dimensional category values.
            read: No-argument reader resampled after each source step.
            source: Existing data source to display.
            field_id: Advanced identifier for data already declared by a
                backend. Prefer `source` in normal authoring code.
            series: Category labels. Required with `read` because labels
                cannot be inferred from future values.
            by: Name of the category dimension.
            unit: Unit shown on the y axis.
            levels: Horizontal reference levels.
            panel_id: Explicit panel identifier for advanced layout integration.
            **style: Plot styling such as `title`, `x_label`, `y_label`,
                `y_min`, `y_max`, `color`, `colors`,
                `background_color`, `show_legend`, and
                `max_refresh_hz`.

        Returns:
            A handle accepted by `cnv.layout()`.

        Provide exactly one data path: `values`/`read` for data owned by
        this source, or `source`/`field_id` for existing data.
        """
        slug = _slug(name)
        view_id = f"{slug}_bar"
        resolved_panel_id = panel_id or f"{slug}-panel"
        category_dim = by or (source.series_dim if source is not None else None) or "series"
        owns_data = values is not None or read is not None

        field_builders: tuple = ()
        if owns_data:
            if source is not None or field_id is not None:
                raise ValueError("bar(...) takes values=/read=, or source=/field_id=, not both")
            binding = self._declare_field(
                field_id=f"{slug}_field",
                dim=category_dim,
                labels=_category_labels(series, values, name),
                values=values,
                read=read,
                unit=unit,
            )
            resolved_field_id = binding.field_id
            field_builders = (lambda backend, _binding=binding: _binding.field_spec(),)
        else:
            resolved_field_id = field_id or (source.field_id if source is not None else None)
            if resolved_field_id is None:
                raise ValueError("bar(...) requires values=..., read=..., source=..., or field_id=...")
            if source is not None and source.unit is not None and unit is None:
                unit = source.unit
        if unit is not None and "y_unit" not in style:
            style = {**style, "y_unit": unit}
        title = style.pop("title", name)
        self._widgets.append(
            BarPlotWidget(
                field_id=resolved_field_id,
                view_id=view_id,
                panel_id=resolved_panel_id,
                title=title,
                category_dim=category_dim,
                levels=levels,
                field_builders=field_builders,
                style=style,
            )
        )
        return BarHandle(resolved_panel_id)

    def state_graph(
        self,
        name: str,
        *,
        node_positions: tuple[tuple[str, float, float], ...],
        edges: tuple[tuple[str, str, str], ...],
        node_values: Any = None,
        node_read: Callable[[], Any] | None = None,
        node_source: FieldSource | None = None,
        edge_values: Any = None,
        edge_read: Callable[[], Any] | None = None,
        edge_source: FieldSource | None = None,
        node_names: Sequence[str] | None = None,
        edge_names: Sequence[str] | None = None,
        panel_id: str | None = None,
        **style: Any,
    ) -> StateGraphHandle:
        """A fixed directed graph whose nodes and edges are colored by live data.

        Args:
            name: User-facing graph name and default panel title.
            node_positions: `(node_name, x, y)` tuples in normalized canvas
                coordinates.
            edges: `(source_node, target_node, edge_name)` tuples.
            node_values: Static node values.
            node_read: No-argument reader for live node values.
            node_source: Existing source of node values.
            edge_values: Static edge values.
            edge_read: No-argument reader for live edge values.
            edge_source: Existing source of edge values.
            node_names: Labels defining node-value order. Defaults to names in
                `node_positions`.
            edge_names: Labels defining edge-value order. Defaults to names in
                `edges`.
            panel_id: Explicit panel identifier for advanced layout integration.
            **style: Graph styling such as color maps, color limits, node size,
                edge width, arrow size, label size, background color, and
                `max_refresh_hz`.

        Returns:
            A handle accepted by `cnv.layout()`.

        For each of nodes and edges, use one of `*_values`, `*_read`, or
        `*_source`. Omitted values start at zero.
        """
        slug = _slug(name)
        view_id = f"{slug}_graph"
        resolved_panel_id = panel_id or f"{slug}-panel"
        node_labels = tuple(node_names or [item[0] for item in node_positions])
        edge_labels = tuple(edge_names or [item[2] for item in edges])
        title = style.pop("title", name)

        node_field_id, node_builder = self._graph_field(
            f"{slug}_nodes", "state", node_labels, node_values, node_read, node_source
        )
        edge_field_id, edge_builder = self._graph_field(
            f"{slug}_edges", "edge", edge_labels, edge_values, edge_read, edge_source
        )
        self._widgets.append(
            StateGraphWidget(
                view_id=view_id,
                panel_id=resolved_panel_id,
                title=title,
                node_field_id=node_field_id,
                edge_field_id=edge_field_id,
                node_positions=tuple(node_positions),
                edges=tuple(edges),
                field_builders=tuple(b for b in (node_builder, edge_builder) if b is not None),
                style=style,
            )
        )
        return StateGraphHandle(resolved_panel_id)

    def _graph_field(self, field_id, dim, labels, values, read, source):
        if source is not None:
            if values is not None or read is not None:
                raise ValueError(f"state_graph(...) {dim} takes values/read, or a source, not both")
            return source.field_id, None
        if values is None and read is None:
            values = np.zeros(len(labels), dtype=np.float32)
        binding = self._declare_field(
            field_id=field_id, dim=dim, labels=labels, values=values, read=read
        )
        return binding.field_id, (lambda backend, _binding=binding: _binding.field_spec())

    def _declare_field(self, *, field_id, dim, labels, values, read, unit=None) -> ArrayFieldBinding:
        binding = ArrayFieldBinding(
            field_id=field_id, dim=dim, labels=tuple(labels), values=values, read=read, unit=unit
        )
        self._fields.append(binding)
        return binding

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
    ) -> MorphologyHandle:
        """Render custom morphology geometry, optionally colored by per-entity values.

        Args:
            geometry: Morphology geometry to render.
            name: User-facing panel title.
            values: Static scalar value for each geometry entity.
            read: No-argument reader for live per-entity scalar values.
            unit: Unit of the color values.
            color_limits: Fixed `(minimum, maximum)` color range.
            color_map: Registered color-map name.
            color_norm: Color normalization mode.
            background_color: Canvas background color.
            max_refresh_hz: Maximum morphology repaint rate, or `None` for
                every available update.
            selected: Initial entity id in single-select mode, or an iterable
                of ids in multi-select mode.
            selectable: Whether pointer clicks change selection.
            select_multiple: Whether more than one entity can be selected.
            panel: Whether to create the visible 3D panel.

        Returns:
            A morphology handle. `handle.selected` references selection state;
            simulator-backed handles may also expose `handle.selection` as an
            optimized data source for `line()`.

        Supply at most one of `values` and `read`. An empty or omitted
        `selected` value starts with no selection.
        """
        if not isinstance(geometry, MorphologyGeometrySpec):
            raise TypeError("morphology(...) expects geometry to be a MorphologyGeometrySpec")
        if select_multiple and not selectable:
            raise ValueError("morphology(select_multiple=True) requires selectable=True")
        if values is not None and read is not None:
            raise ValueError("morphology(...) accepts values=... or read=..., not both")

        slug = _slug(name)
        view_id = slug
        panel_id = f"{slug}-panel"
        color_field_id = None
        field_builders: tuple = ()
        if values is not None or read is not None:
            binding = self._declare_field(
                field_id=f"{slug}_values",
                dim="segment",
                labels=geometry.entity_ids,
                values=values,
                read=read,
                unit=unit,
            )
            color_field_id = binding.field_id
            field_builders = (lambda backend, _binding=binding: _binding.field_spec(),)

        self._geometries.append(geometry)
        self._add_widget(geometries=(geometry,), field_builders=field_builders)

        selection_key = SELECTED_ENTITY_IDS_KEY
        self._selection_modes[selection_key] = select_multiple
        if selected is not None:
            selected_ids = _selection_to_internal(selected, select_multiple=select_multiple)
            self._initial_values.append((selection_key, selected_ids))
            active_id = selected_ids[0] if selected_ids else None
            self._initial_values.append((SELECTED_ENTITY_ID_KEY, active_id))
            if active_id is not None:
                self._initial_values.append(("selected_entity_label", geometry.label_for(active_id)))

        self._add_morphology_widget(
            view_id=view_id,
            panel_id=panel_id,
            title=name,
            geometry_id=geometry.id,
            color_field_id=color_field_id,
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
            panel=panel,
        )
        return MorphologyHandle(
            id=panel_id,
            selected=SelectionRef(selection_key, select_multiple=select_multiple),
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
        **view_kwargs: Any,
    ) -> SurfaceHandle:
        """Add a 3D surface panel from a two-dimensional array.

        Args:
            name: User-facing surface name and default panel title.
            values: Static two-dimensional values.
            read: No-argument reader returning updated two-dimensional values.
            x: Coordinates for array columns. Defaults to integer indices.
            y: Coordinates for array rows. Defaults to integer indices.
            x_dim: Name of the column dimension.
            y_dim: Name of the row dimension.
            unit: Unit of the surface values.
            camera_distance: Initial camera distance. `None` lets the
                frontend choose.
            camera_elevation: Initial camera elevation in degrees.
            camera_azimuth: Initial camera azimuth in degrees.
            **view_kwargs: Surface styling such as `color_map`,
                `color_limits`, `color_by`, `surface_color`,
                `surface_shading`, `surface_alpha`, `background_color`,
                axis settings, and `max_refresh_hz`. Control handles and value
                references may be used for dynamic properties.

        Returns:
            A surface handle accepted by `grid_slice()` and `cnv.layout()`.
        """
        if values is None and read is None:
            raise ValueError("surface(...) requires values=... or read=...")
        binding = SurfaceBinding(
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
            view_kwargs=dict(view_kwargs),
        )
        binding._register(len(self._surfaces))
        self._surfaces.append(binding)
        return SurfaceHandle(binding)

    def grid_slice(
        self,
        name: str,
        *,
        surface: SurfaceHandle,
        axis: Any,
        position: Any,
        overlay: dict[str, Any] | None = None,
        **line_kwargs: Any,
    ) -> GridSliceHandle:
        """Add a line plot showing one cross-section of a surface.

        Args:
            name: User-facing slice name and default panel title.
            surface: Surface handle returned by `surface()`.
            axis: Axis to cut, usually `"x"` or `"y"`. A dropdown handle
                may be supplied for interactive selection.
            position: Coordinate along the cut axis. A slider handle may be
                supplied for interactive movement.
            overlay: Optional surface-overlay styling.
            **line_kwargs: Line-plot styling accepted by `line()`.

        Returns:
            A grid-slice handle accepted by `cnv.layout()`.
        """
        binding = GridSliceBinding(
            name=name,
            surface=surface._binding,
            axis=axis,
            position=position,
            line_kwargs=dict(line_kwargs),
            overlay_kwargs={} if overlay is None else dict(overlay),
        )
        binding._register(len(self._grid_slices))
        self._grid_slices.append(binding)
        return GridSliceHandle(binding)

    def _register_control(
        self,
        name: str,
        *,
        label: str,
        get: Callable[[], Any] | None = None,
        set: Callable[[BackendInteractionContext, Any], None] | None = None,
        default: Any = 0.0,
        value_spec: ControlValueSpec,
        presentation: ControlPresentationSpec | None = None,
        send_to_backend: bool | None = None,
        handle_type: type[ControlHandle] = ControlHandle,
    ) -> ControlHandle:
        binding = ControlBinding(
            name=name,
            label=label,
            get=get,
            set=set,
            default=default,
            value_spec=value_spec,
            presentation=presentation,
            send_to_backend=send_to_backend,
        )
        self._add_control(binding)
        return handle_type(binding)

    # -- typed control calls -------------------------------------------------
    # One call per widget kind, mirroring matplotlib widgets / Streamlit. Each
    # typed call chooses the value spec and presentation directly; there is no
    # generic source-level escape hatch for arbitrary control specs.

    @staticmethod
    def _initial(default: Any, get: Callable[[], Any] | None, fallback: Any) -> Any:
        if default is not None:
            return default
        if get is not None:
            return get()
        return fallback

    def slider(
        self,
        name: str,
        *,
        label: str,
        min: float,
        max: float,
        get: Callable[[], Any] | None = None,
        set: Callable[[BackendInteractionContext, Any], None] | None = None,
        default: float | None = None,
        steps: int = 100,
        scale: str = "linear",
        int: bool = False,
        send_to_backend: bool | None = None,
    ) -> SliderHandle:
        """Add a horizontal numeric slider.

        Args:
            name: Stable control name.
            label: User-facing label.
            min: Minimum allowed value.
            max: Maximum allowed value.
            get: Optional no-argument reader for the current model value.
            set: Optional callback called as `set(ctx, value)`.
            default: Initial value. When omitted, uses `get()` or `min`.
            steps: Number of slider intervals.
            scale: `"linear"` or `"log"`.
            int: Round values and expose integer slider steps.
            send_to_backend: Override whether changes are sent to the backend.
                By default this is true when `set` is provided.

        Returns:
            A slider handle usable in dynamic view properties and value APIs.
        """
        raw = self._initial(default, get, min)
        value_spec = ScalarValueSpec(
            default=round(float(raw)) if int else float(raw),
            min=min, max=max, value_type="int" if int else "float",
        )
        return self._register_control(
            name, label=label, get=get, set=set, value_spec=value_spec,
            presentation=ControlPresentationSpec(kind="slider", steps=steps, scale=scale),
            send_to_backend=send_to_backend,
            handle_type=SliderHandle,
        )

    def number(
        self,
        name: str,
        *,
        label: str,
        min: int,
        max: int,
        get: Callable[[], Any] | None = None,
        set: Callable[[BackendInteractionContext, Any], None] | None = None,
        default: int | None = None,
        send_to_backend: bool | None = None,
    ) -> NumberHandle:
        """Add an integer spinbox.

        Args:
            name: Stable control name.
            label: User-facing label.
            min: Minimum allowed integer.
            max: Maximum allowed integer.
            get: Optional no-argument reader for the current model value.
            set: Optional callback called as `set(ctx, value)`.
            default: Initial value. When omitted, uses `get()` or `min`.
            send_to_backend: Override whether changes are sent to the backend.

        Returns:
            A number-control handle.
        """
        value_spec = ScalarValueSpec(
            default=int(round(float(self._initial(default, get, min)))), min=min, max=max, value_type="int"
        )
        return self._register_control(
            name, label=label, get=get, set=set, value_spec=value_spec,
            presentation=ControlPresentationSpec(kind="spinbox"),
            send_to_backend=send_to_backend,
            handle_type=NumberHandle,
        )

    def dropdown(
        self,
        name: str,
        *,
        label: str,
        options: Sequence[str],
        get: Callable[[], Any] | None = None,
        set: Callable[[BackendInteractionContext, Any], None] | None = None,
        default: str | None = None,
        send_to_backend: bool | None = None,
    ) -> DropdownHandle:
        """Add a single-select dropdown.

        Args:
            name: Stable control name.
            label: User-facing label.
            options: Non-empty sequence of displayed string values.
            get: Optional no-argument reader for the current model value.
            set: Optional callback called as `set(ctx, value)`.
            default: Initially selected option. When omitted, uses `get()` or
                the first option.
            send_to_backend: Override whether changes are sent to the backend.

        Returns:
            A dropdown handle usable in dynamic view properties and value APIs.
        """
        opts = tuple(str(option) for option in options)
        value_spec = ChoiceValueSpec(default=str(self._initial(default, get, opts[0])), options=opts)
        return self._register_control(
            name, label=label, get=get, set=set, value_spec=value_spec,
            presentation=ControlPresentationSpec(kind="dropdown"),
            send_to_backend=send_to_backend,
            handle_type=DropdownHandle,
        )

    def checkbox(
        self,
        name: str,
        *,
        label: str,
        get: Callable[[], Any] | None = None,
        set: Callable[[BackendInteractionContext, Any], None] | None = None,
        default: bool | None = None,
        send_to_backend: bool | None = None,
    ) -> CheckboxHandle:
        """Add a boolean checkbox.

        Args:
            name: Stable control name.
            label: User-facing label.
            get: Optional no-argument reader for the current model value.
            set: Optional callback called as `set(ctx, value)`.
            default: Initial checked state. When omitted, uses `get()` or
                `False`.
            send_to_backend: Override whether changes are sent to the backend.

        Returns:
            A checkbox handle usable in dynamic view properties and value APIs.
        """
        value_spec = BoolValueSpec(default=bool(self._initial(default, get, False)))
        return self._register_control(
            name, label=label, get=get, set=set, value_spec=value_spec,
            presentation=ControlPresentationSpec(kind="checkbox"),
            send_to_backend=send_to_backend,
            handle_type=CheckboxHandle,
        )

    def text(
        self,
        name: str,
        *,
        label: str,
        get: Callable[[], Any] | None = None,
        set: Callable[[BackendInteractionContext, Any], None] | None = None,
        default: str | None = None,
        placeholder: str = "",
        max_length: int | None = None,
        send_to_backend: bool | None = None,
    ) -> TextHandle:
        """Add a single-line text field.

        Args:
            name: Stable control name.
            label: User-facing label.
            get: Optional no-argument reader for the current model value.
            set: Optional callback called as `set(ctx, value)`.
            default: Initial text. When omitted, uses `get()` or an empty
                string.
            placeholder: Hint shown while the field is empty.
            max_length: Maximum number of characters, or `None` for no limit.
            send_to_backend: Override whether changes are sent to the backend.

        Returns:
            A text-control handle.
        """
        value_spec = TextValueSpec(
            default=str(self._initial(default, get, "")), placeholder=placeholder, max_length=max_length
        )
        return self._register_control(
            name, label=label, get=get, set=set, value_spec=value_spec,
            presentation=ControlPresentationSpec(kind="text"),
            send_to_backend=send_to_backend,
            handle_type=TextHandle,
        )

    def xy_pad(
        self,
        name: str,
        *,
        label: str,
        x: tuple[str, float, float] = ("X", 0.0, 1.0),
        y: tuple[str, float, float] = ("Y", 0.0, 1.0),
        get: Callable[[], Any] | None = None,
        set: Callable[[BackendInteractionContext, Any], None] | None = None,
        default: Mapping[str, float] | None = None,
        send_to_backend: bool | None = None,
    ) -> XYPadHandle:
        """Add a draggable two-dimensional value pad.

        Args:
            name: Stable control name.
            label: User-facing label.
            x: `(axis_label, minimum, maximum)` for the x axis.
            y: `(axis_label, minimum, maximum)` for the y axis.
            get: Optional no-argument reader returning an `{"x": ..., "y": ...}`
                mapping.
            set: Optional callback called as `set(ctx, value)`.
            default: Initial x/y mapping. Defaults to the center of both axes.
            send_to_backend: Override whether changes are sent to the backend.

        Returns:
            An XY-pad handle usable in dynamic view properties and value APIs.
        """
        x_label, x_min, x_max = x
        y_label, y_min, y_max = y
        resolved = default if default is not None else (get() if get is not None else None)
        if resolved is None:
            resolved = {"x": (x_min + x_max) / 2.0, "y": (y_min + y_max) / 2.0}
        value_spec = XYValueSpec(
            default=dict(resolved), x_range=(x_min, x_max), y_range=(y_min, y_max),
            x_label=x_label, y_label=y_label,
        )
        return self._register_control(
            name, label=label, get=get, set=set, value_spec=value_spec,
            send_to_backend=send_to_backend,
            handle_type=XYPadHandle,
        )

    def button(
        self,
        name: str,
        *,
        label: str,
        fn: Callable[[BackendInteractionContext], None],
    ) -> ActionHandle:
        """Add a button to the controls panel.

        Args:
            name: Stable action name.
            label: User-facing button label.
            fn: Callback invoked as `fn(ctx)` on the backend.

        Returns:
            An action handle that can also be passed to `hotkey()`.

        The context provides value access, status messages, `clear()`, and
        `reset()`.
        """
        binding = ActionBinding(name=name, label=label, fn=fn)
        self._add_action(binding)
        return ActionHandle(binding)

    def hotkey(
        self,
        key: str | Sequence[str],
        target: "ActionHandle | Callable[[BackendInteractionContext], None] | None" = None,
        *,
        fn: Callable[[BackendInteractionContext], None] | None = None,
    ) -> ActionHandle:
        """Bind a key (or keys) to an effect.

        Args:
            key: Key-sequence string, or a sequence of strings, such as `"r"`,
                `"Escape"`, or `"Ctrl+R"`.
            target: Existing action handle to reuse, or a callback invoked as
                `target(ctx)`.
            fn: Explicit callback alternative to a callable `target`.

        Returns:
            The reused or newly created action handle.
        """
        keys = (key,) if isinstance(key, str) else tuple(key)
        if isinstance(target, ActionHandle):
            binding = target._binding
            binding.shortcuts = tuple(binding.shortcuts) + keys
            return target
        handler = target if callable(target) else fn
        if handler is None:
            raise ValueError("hotkey(...) needs a button handle, a callable, or fn=")
        binding = ActionBinding(
            name=f"hotkey_{'_'.join(keys)}",
            label="",
            fn=handler,
            shortcuts=keys,
            show_button=False,
        )
        self._add_action(binding)
        return ActionHandle(binding)

    def create_value(self, name: str | ValueRef, *, initial: Any = _MISSING) -> ValueRef:
        """Create named runtime state for controls and dynamic view properties.

        Args:
            name: Value name, or an existing value reference to reuse.
            initial: Optional initial value. Omit it to leave the value unset.

        Returns:
            A value reference accepted by `ctx.get_value()`,
            `ctx.set_value()`, selectors, levels, and dynamic view options.
        """
        ref = name if isinstance(name, ValueRef) else ValueRef(str(name))
        if initial is not _MISSING:
            self._initial_values.append((ref.key, initial))
        return ref

    def derive_value(
        self,
        name: str,
        fn: Callable[[], Any],
        *,
        max_refresh_hz: float | None = 10.0,
        initial: Any = None,
    ) -> ValueRef:
        """Create a runtime value derived from a Python callable.

        Args:
            name: Stable value name.
            fn: No-argument callable returning the current value.
            max_refresh_hz: Maximum evaluation frequency. `None` or a
                non-positive value evaluates whenever the source updates.
            initial: Value available before the first evaluation.

        Returns:
            A value reference accepted anywhere a dynamic value is supported.
        """
        ref = ValueRef(str(name))
        self._derived_values.append(
            DerivedValueBinding(name=ref.key, fn=fn, max_refresh_hz=max_refresh_hz, initial=initial)
        )
        return ref

    @property
    def controls_panel(self) -> PanelHandle:
        """Handle for the auto-generated controls panel, for use in ``cnv.layout``."""
        return PanelHandle("controls-panel")

    def show(self):
        """Launch this source by itself.

        Prefer `cnv.show()` when multiple sources may contribute to one app.

        Returns:
            The runtime app handle.
        """
        return self.launch()

    def _add_widget(
        self,
        *,
        field_builders: Sequence[Any] = (),
        geometries: Sequence[Any] = (),
        views: Sequence[Any] = (),
        panel: Any = None,
        controls: Sequence[Any] = (),
    ) -> None:
        self._panel_bindings.append(
            SpecWidget(
                field_builders=tuple(field_builders),
                geometries=tuple(geometries),
                views=tuple(views),
                panel=panel,
                controls=tuple(controls),
            )
        )

    def _add_morphology_widget(
        self,
        *,
        view_id: str,
        panel_id: str,
        title: Any,
        geometry_id: str | Callable[[Any], str],
        color_field_id: str | None,
        entity_dim: str = "segment",
        sample_dim: str | None = None,
        selectable: bool = True,
        style: Mapping[str, Any] | None = None,
        panel: bool = True,
    ) -> PanelHandle:
        if panel:
            self._panel_bindings.append(
                MorphologyWidget(
                    view_id=view_id,
                    panel_id=panel_id,
                    title=title,
                    geometry_id=geometry_id,
                    color_field_id=color_field_id,
                    entity_dim=entity_dim,
                    sample_dim=sample_dim,
                    selectable=selectable,
                    style={} if style is None else dict(style),
                )
            )
        return PanelHandle(panel_id)
    def _panel_bindings_for_compose(self) -> tuple[Any, ...]:
        return (*self._widgets, *self._panel_bindings, *self._surfaces, *self._grid_slices, *self._traces)

    def _uses_field(self, field_id: str) -> bool:
        for widget in self._panel_bindings_for_compose():
            if getattr(widget, "field_id", None) == field_id:
                return True
            if getattr(widget, "color_field_id", None) == field_id:
                return True
            for view in getattr(widget, "views", ()):
                if callable(view):
                    continue
                if getattr(view, "field_id", None) == field_id:
                    return True
                if getattr(view, "color_field_id", None) == field_id:
                    return True
        return False

    def _compose_startup_data_app_spec_for_backend(
        self,
        backend: BackendBase,
        *,
        expected_backend_type: Any | None = None,
        history_field_id: str | None = None,
    ) -> AppSpec:
        if expected_backend_type is not None and not isinstance(backend, expected_backend_type):
            raise TypeError(
                f"{type(self).__name__} expected {expected_backend_type.__name__}, got {type(backend).__name__}"
            )
        if history_field_id is not None:
            set_history_enabled = getattr(backend, "set_history_enabled", None)
            if callable(set_history_enabled):
                set_history_enabled(self._uses_field(history_field_id))
        build = getattr(backend, "build_startup_data", None)
        if not callable(build):
            raise TypeError(f"{type(backend).__name__} does not provide build_startup_data()")
        return append_bindings_to_app_spec(
            build(),
            panel_bindings=self._panel_bindings_for_compose(),
            controls=self._controls,
            actions=self._actions,
            backend=backend,
        )

    def launch(self):
        """Launch this source directly and return its app handle.

        Prefer `cnv.show()` for normal authoring so all registered sources
        can be integrated.
        """
        from compneurovis._source_runtime import launch_source

        return launch_source(self)

    def _make_backend(self) -> BackendBase:
        raise NotImplementedError

    def _build_app_spec_for_backend(self, backend: BackendBase) -> AppSpec:
        # Uniform for every source: compose the raw app-spec, then apply the
        # app-level ``cnv.layout`` grid. No source (generic, neuron, jaxley)
        # special-cases layout -- they only produce panels.
        return apply_panel_grid(self._compose_app_spec_for_backend(backend), self._panel_grid)

    def _compose_app_spec_for_backend(self, backend: BackendBase) -> AppSpec:
        build = getattr(backend, "build_startup_app_spec", None)
        if not callable(build):
            raise TypeError(f"{type(backend).__name__} does not provide build_startup_app_spec()")
        return append_bindings_to_app_spec(
            build(),
            panel_bindings=self._panel_bindings_for_compose(),
            controls=self._controls,
            actions=self._actions,
            backend=backend,
        )

    def _add_trace(self, binding: TraceBinding) -> None:
        binding._register(len(self._traces))
        self._traces.append(binding)

    def _add_control(self, binding: ControlBinding) -> None:
        binding._register(len(self._controls))
        self._controls.append(binding)

    def _add_action(self, binding: ActionBinding) -> None:
        binding._register(len(self._actions))
        self._actions.append(binding)


class InlineSource(InlineSourceBase):
    """Generic source returned by `cnv.source()`."""

    def __init__(
        self,
        source_like: Callable[[BackendInteractionContext], None] | Iterator | None = None,
        *,
        title: str = "CompNeuroVis",
    ) -> None:
        super().__init__(title=title)
        self._source_like = source_like

    def _make_backend(self) -> InlineBackend:
        is_callable = callable(self._source_like)
        iterator = None
        if self._source_like is not None and not is_callable:
            iterator = iter(self._source_like)
        return InlineBackend(
            traces=self._traces,
            controls=self._controls,
            actions=self._actions,
            surfaces=self._surfaces,
            fields=self._fields,
            derived_values=self._derived_values,
            initial_values=self._initial_values,
            geometries=self._geometries,
            selection_modes=self._selection_modes,
            step=self._source_like if is_callable else None,
            iterator=iterator,
        )

    def _compose_app_spec_for_backend(self, backend: BackendBase) -> AppSpec:
        del backend
        return _build_inline_app_spec(
            title=self._app_title or self.title,
            traces=self._traces,
            controls=self._controls,
            actions=self._actions,
            surfaces=self._surfaces,
            grid_slices=self._grid_slices,
            widgets=(*self._widgets, *self._panel_bindings),
        )


class ComposedSource(InlineSourceBase):
    """Neutral authoring-layer composition of source declarations."""

    def __init__(
        self,
        sources: tuple[Any, ...],
        *,
        title: str | None = None,
    ) -> None:
        if len(sources) < 2:
            raise ValueError("ComposedSource requires at least two sources")
        super().__init__(title=title or "CompNeuroVis")
        self.sources = tuple(sources)

    def _make_backend(self) -> BackendBase:
        raise NotImplementedError(
            "ComposedSource does not lower to a single backend wrapper. "
            "Composition must compile to explicit multi-actor RunSpec wiring."
        )

    def _compose_app_spec_for_backend(self, backend: BackendBase) -> AppSpec:
        del backend
        raise NotImplementedError(
            "ComposedSource AppSpec compilation needs a multi-source runtime compiler. "
            "No source is privileged to provide the composed AppSpec."
        )


class RemoteSource(InlineSourceBase):
    """Source adapter for an actor hosted outside the current Python process."""

    def __init__(self, actor_ref: RemoteActorRef, *, title: str = "CompNeuroVis") -> None:
        super().__init__(title=title)
        self._actor_ref = actor_ref

    def _make_backend(self) -> BackendBase:
        raise NotImplementedError(
            "RemoteSource does not create a local backend. "
            "Remote source compilation to RunSpec is not yet implemented."
        )

    def _compose_app_spec_for_backend(self, backend: BackendBase) -> AppSpec:
        raise NotImplementedError("RemoteSource AppSpec comes from the remote actor.")


def apply_panel_grid(
    app_spec: AppSpec,
    panel_grid: tuple[tuple[str, ...], ...] | None,
) -> AppSpec:
    """Set the active layout's panel grid from an app-level ``cnv.layout``.

    Shared by every source so layout handling is uniform: a source produces its
    panels, and this applies the arrangement afterward -- once all panels exist
    (including any auto-generated controls panel). Returns ``app_spec`` unchanged
    when no grid was declared.
    """
    if panel_grid is None:
        return app_spec
    layouts = dict(app_spec.layout_catalog.layouts)
    active = app_spec.layout_catalog.active
    layouts[active] = replace(layouts[active], panel_grid=panel_grid)
    return replace(app_spec, layout_catalog=LayoutCatalog(layouts=layouts, active=active))


def _build_inline_app_spec(
    *,
    title: str,
    traces: list[TraceBinding],
    controls: list[ControlBinding],
    actions: list[ActionBinding],
    surfaces: list[SurfaceBinding],
    grid_slices: list[GridSliceBinding],
    widgets: list[Any],
) -> AppSpec:
    app_spec = AppSpec(
        data=DataCatalog(),
        view_catalog=ViewCatalog(),
        interactions=InteractionCatalog(),
        layout_catalog=LayoutCatalog.single(LayoutSpec(title=title)),
    )
    return append_bindings_to_app_spec(
        app_spec,
        panel_bindings=(*widgets, *surfaces, *grid_slices, *traces),
        controls=controls,
        actions=actions,
    )


__all__ = [
    "ComposedSource",
    "InlineSource",
    "InlineSourceBase",
    "RemoteActorRef",
    "RemoteSource",
]

