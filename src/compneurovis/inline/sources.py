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
from compneurovis.core.field import FieldSpec
from compneurovis.core.geometry import MorphologyGeometrySpec
from compneurovis.backends.interaction import (
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
    """Base for anything that can participate in inline authoring mode."""

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
        """One bar per category (the coord labels of the category dim).

        Supply the data directly -- ``values`` for a static bar chart, ``read``
        for one resampled every tick, exactly as ``surface`` does -- or point at
        a field some other widget or backend already declares via ``source`` /
        ``field_id``. With ``read`` the category labels cannot be inferred, so
        pass ``series``.
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

        ``node_positions`` are ``(state, x, y)`` in normalized canvas space and
        ``edges`` are ``(source_state, target_state, edge)``. Node occupancies and
        edge fluxes follow the same data vocabulary as every other widget:
        ``*_values`` for static, ``*_read`` for resampled each tick, ``*_source``
        to read a field a backend already declares. Omit them for an empty graph.
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

        Users provide geometry and optional values/readers. The backend field
        that carries those values is an implementation detail, matching the rest
        of the inline API: authors name the view they want, not storage IDs.
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
        set: Callable[[Any, Any], None] | None = None,
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
        set: Callable[[Any, Any], None] | None = None,
        default: float | None = None,
        steps: int = 100,
        scale: str = "linear",
        int: bool = False,
        send_to_backend: bool | None = None,
    ) -> SliderHandle:
        """A horizontal slider. ``scale="log"`` for a log axis; ``int=True`` for
        integer-valued steps."""
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
        set: Callable[[Any, Any], None] | None = None,
        default: int | None = None,
        send_to_backend: bool | None = None,
    ) -> NumberHandle:
        """An integer spinbox."""
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
        set: Callable[[Any, Any], None] | None = None,
        default: str | None = None,
        send_to_backend: bool | None = None,
    ) -> DropdownHandle:
        """A single-select dropdown over ``options``."""
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
        set: Callable[[Any, Any], None] | None = None,
        default: bool | None = None,
        send_to_backend: bool | None = None,
    ) -> CheckboxHandle:
        """A boolean checkbox."""
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
        set: Callable[[Any, Any], None] | None = None,
        default: str | None = None,
        placeholder: str = "",
        max_length: int | None = None,
        send_to_backend: bool | None = None,
    ) -> TextHandle:
        """A single-line text field."""
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
        set: Callable[[Any, Any], None] | None = None,
        default: Mapping[str, float] | None = None,
        send_to_backend: bool | None = None,
    ) -> XYPadHandle:
        """A 2D draggable pad over ``x=(label, min, max)`` and ``y=(label, min, max)``."""
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
        fn: Callable[[Any], None],
    ) -> ActionHandle:
        """A labeled button in the controls panel that runs ``fn(ctx)`` on click."""
        binding = ActionBinding(name=name, label=label, fn=fn)
        self._add_action(binding)
        return ActionHandle(binding)

    def hotkey(
        self,
        key: str | Sequence[str],
        target: "ActionHandle | Callable[[Any], None] | None" = None,
        *,
        fn: Callable[[Any], None] | None = None,
    ) -> ActionHandle:
        """Bind a key (or keys) to an effect.

        ``target`` is either a button/hotkey handle -- wire the key to that same
        effect -- or a callable for a standalone key-only effect (``fn=`` is the
        explicit form of the latter). Keys are ``QKeySequence`` strings, so ``"r"``,
        ``"escape"``, and ``"Ctrl+R"`` all work. Returns the effect handle.
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
    """Adapter for a callable, iterator, or static source."""

    def __init__(
        self,
        source_like: Callable[[Any], None] | Iterator | None = None,
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

