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
from compneurovis.core.controls import ControlPresentationSpec, ControlValueSpec
from compneurovis.core.field import FieldSpec
from compneurovis.core.messages import InvokeAction, MessagePayload, Reset
from compneurovis.inline.backend import InlineBackend
from compneurovis.inline.bindings import (
    ActionBinding,
    ActionHandle,
    BarPlotWidget,
    ControlBinding,
    ControlHandle,
    DerivedValueBinding,
    FieldSource,
    GridSliceBinding,
    GridSliceHandle,
    LinePlotWidget,
    MorphologyWidget,
    PanelHandle,
    SeriesReaders,
    SpecWidget,
    StateGraphWidget,
    SurfaceBinding,
    SurfaceHandle,
    TraceBinding,
    TraceHandle,
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
    ) -> TraceHandle | PanelHandle:
        if read is not None:
            binding = TraceBinding(name=name, read=read, x=x if callable(x) else None, **style)
            self._add_trace(binding)
            return TraceHandle(binding)

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
        return PanelHandle(resolved_panel_id)

    def trace(self, name: str, *, read: SeriesReaders, x: Callable[[], float] | None = None, **kwargs) -> TraceHandle:
        handle = self.line(name, read=read, x=x, **kwargs)
        if not isinstance(handle, TraceHandle):
            raise TypeError("trace(...) requires read=...")
        return handle

    def bar(
        self,
        name: str,
        *,
        source: FieldSource | None = None,
        field_id: str | None = None,
        by: str | None = None,
        levels: Sequence[Any] = (),
        panel_id: str | None = None,
        **style: Any,
    ) -> PanelHandle:
        slug = _slug(name)
        resolved_field_id = field_id or (source.field_id if source is not None else None)
        if resolved_field_id is None:
            raise ValueError("bar(...) requires source=... or field_id=...")
        view_id = f"{slug}_bar"
        resolved_panel_id = panel_id or f"{slug}-panel"
        category_dim = by or (source.series_dim if source is not None else None) or "series"
        if source is not None and source.unit is not None and "y_unit" not in style:
            style = {**style, "y_unit": source.unit}
        title = style.pop("title", name)
        self._widgets.append(
            BarPlotWidget(
                field_id=resolved_field_id,
                view_id=view_id,
                panel_id=resolved_panel_id,
                title=title,
                category_dim=category_dim,
                levels=levels,
                style=style,
            )
        )
        return PanelHandle(resolved_panel_id)

    def state_graph(
        self,
        name: str,
        *,
        node_field_id: str,
        edge_field_id: str,
        node_positions: tuple[tuple[str, float, float], ...],
        edges: tuple[tuple[str, str, str], ...],
        node_names: Sequence[str] | None = None,
        edge_names: Sequence[str] | None = None,
        panel_id: str | None = None,
        **style: Any,
    ) -> PanelHandle:
        slug = _slug(name)
        view_id = f"{slug}_graph"
        resolved_panel_id = panel_id or f"{slug}-panel"
        node_labels = tuple(node_names or [item[0] for item in node_positions])
        edge_labels = tuple(edge_names or [item[2] for item in edges])
        title = style.pop("title", name)
        field_builders = (
            lambda backend: FieldSpec(
                id=node_field_id,
                initial_values=np.zeros(len(node_labels), dtype=np.float32),
                dims=("state",),
                coords={"state": np.asarray(node_labels)},
            ),
            lambda backend: FieldSpec(
                id=edge_field_id,
                initial_values=np.zeros(len(edge_labels), dtype=np.float32),
                dims=("edge",),
                coords={"edge": np.asarray(edge_labels)},
            ),
        )
        self._widgets.append(
            StateGraphWidget(
                view_id=view_id,
                panel_id=resolved_panel_id,
                title=title,
                node_field_id=node_field_id,
                edge_field_id=edge_field_id,
                node_positions=node_positions,
                edges=edges,
                field_builders=field_builders,
                style=style,
            )
        )
        return PanelHandle(resolved_panel_id)

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

    def control(
        self,
        name: str,
        *,
        label: str,
        get: Callable[[], Any] | None = None,
        set: Callable[[Any, Any], None] | None = None,
        min: float = 0.0,
        max: float = 1.0,
        default: Any = 0.0,
        value_spec: ControlValueSpec | None = None,
        presentation: ControlPresentationSpec | None = None,
        send_to_backend: bool | None = None,
    ) -> ControlHandle:
        binding = ControlBinding(
            name=name,
            label=label,
            get=get,
            set=set,
            min=min,
            max=max,
            default=default,
            value_spec=value_spec,
            presentation=presentation,
            send_to_backend=send_to_backend,
        )
        self._add_control(binding)
        return ControlHandle(binding)

    def action(
        self,
        name: str,
        *,
        label: str,
        fn: Callable[[Any], None],
        resets_fields: bool = False,
    ) -> ActionHandle:
        binding = ActionBinding(name=name, label=label, fn=fn, resets_fields=resets_fields)
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
        views: Sequence[Any] = (),
        panel: Any = None,
        controls: Sequence[Any] = (),
    ) -> None:
        self._panel_bindings.append(
            SpecWidget(
                field_builders=tuple(field_builders),
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
            derived_values=self._derived_values,
            initial_values=self._initial_values,
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
            widgets=self._widgets,
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




