"""Authoring-layer source adapters for inline mode."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import replace
from typing import Any, Callable

from compneurovis.backends.base import BackendBase
from compneurovis.core.app_spec import (
    AppSpec,
    DataCatalog,
    InteractionCatalog,
    LayoutCatalog,
    LayoutSpec,
    ViewCatalog,
)
from compneurovis.backends.interaction import BackendInteractionContext
from compneurovis.inline.compiler import (
    SpecBinding,
    Binding,
    append_bindings_to_app_spec,
)
from compneurovis.inline.backend import InlineBackend
from compneurovis.inline.data_producers import (
    SnapshotProducer,
    SeriesProducer,
    DerivedValueProducer,
)
from compneurovis.inline.refs import (
    ControlsRef,
)
from compneurovis.inline.interactions import (
    ActionInteraction,
    ControlInteraction,
    ClickHandler,
    ClickHandlerBinding,
    EntityClickHandler,
    PointerInteractionHandlerBinding,
)
from compneurovis.inline.sources.controls import SourceControls
from compneurovis.inline.widget_registry import _reserve_widget_names
from compneurovis.inline.widgets.source_api import SourceWidgetAPI

_MISSING = object()


class InlineSourceBase(SourceControls, SourceWidgetAPI):
    """Shared high-level authoring API for all source types.

    Sources begin with no panels. Calls such as `line()`,
    `morphology()`, and `surface()` opt views into the app; typed
    control and action methods opt interactions in. Obtain a concrete source
    from `cnv.source()` or a simulator namespace.
    """

    def __init__(self, *, title: str = "CompNeuroVis") -> None:
        self.title = title
        self._app_title: str | None = None
        self._series: list[SeriesProducer] = []
        self._widgets: list[Binding] = []
        self._control_bindings: list[ControlInteraction] = []
        self._actions: list[ActionInteraction] = []
        self._click_handlers: list[ClickHandlerBinding] = []
        self._pointer_interaction_handlers: list[
            PointerInteractionHandlerBinding
        ] = []
        self._controls_panels: dict[str, ControlsRef] = {}
        self._controls_panel_kinds: dict[str, str] = {}
        self._active_controls_panel_id: str | None = None
        self._fields: list[SnapshotProducer] = []
        self._derived_values: list[DerivedValueProducer] = []
        self._initial_values: list[tuple[str, Any]] = []
        self._widget_namespace_index = 0
        self._panel_grid: tuple[tuple[str, ...], ...] | None = None
        self._handle = None

    def interactions(
        self,
        *,
        click: ClickHandler | None = None,
        entity_click: EntityClickHandler | None = None,
    ) -> None:
        """Attach application-wide advanced interaction behavior.

        Reusable widgets should prefer ``context.on_entity_click(...)``, which
        scopes behavior to one exact interaction. This source-level form is for
        applications that intentionally observe every authored click. Returning
        truthy consumes a click before its optional default selection mutation.
        """
        if click is None and entity_click is None:
            raise ValueError("interactions(...) requires click=... or entity_click=...")
        if click is not None:
            self._click_handlers.append(ClickHandlerBinding(fn=click))
        if entity_click is not None:
            self._click_handlers.append(
                ClickHandlerBinding(
                    fn=lambda context, event, _fn=entity_click: _fn(
                        context, str(event.value)
                    ),
                    result_kind="entity",
                )
            )

    def _declare_field(
        self,
        *,
        field_id: str,
        dim: str,
        labels: Sequence[Any],
        values: Any,
        read: Callable[[], Any] | None,
        unit: str | None = None,
    ) -> SnapshotProducer:
        # 1-D convenience wrapper: a labelled series is just the rank-1 case of
        # the general producer, with the labels serving as the dim's coords.
        return self._declare_grid_field(
            field_id=field_id,
            dims=(dim,),
            coords={dim: tuple(labels)},
            values=values,
            read=read,
            unit=unit,
        )

    def _declare_grid_field(
        self,
        *,
        field_id: str,
        dims: tuple[str, ...],
        coords: dict[str, Any],
        values: Any,
        read: Callable[[], Any] | None,
        unit: str | None = None,
        replace_includes_coords: bool = False,
    ) -> SnapshotProducer:
        producer = SnapshotProducer(
            field_id=field_id,
            dims=dims,
            coords=dict(coords),
            values=values,
            read=read,
            unit=unit,
            replace_includes_coords=replace_includes_coords,
        )
        self._fields.append(producer)
        return producer

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
        self._widgets.append(
            SpecBinding(
                field_builders=tuple(field_builders),
                geometries=tuple(geometries),
                views=tuple(views),
                panel=panel,
                controls=tuple(controls),
            )
        )

    def _bindings_for_compose(self) -> tuple[Binding, ...]:
        # Series producers are runtime-only; public widget declarations in
        # ``_widgets`` carry their fields and views into AppSpec.
        return tuple(self._widgets)

    def _uses_field(self, field_id: str) -> bool:
        for binding in self._bindings_for_compose():
            if getattr(binding, "field_id", None) == field_id:
                return True
            if getattr(binding, "color_field_id", None) == field_id:
                return True
            if field_id in getattr(binding, "field_retention", {}):
                return True
            for specs_name in ("views", "operators", "visual_contributions"):
                for spec in getattr(binding, specs_name, ()):
                    if callable(spec):
                        continue
                    if field_id in getattr(spec, "inputs", {}).values():
                        return True
        return False

    def _compose_startup_data_app_spec_for_backend(
        self,
        backend: BackendBase,
        *,
        expected_backend_type: Any | None = None,
        history_field_id: str | None = None,
    ) -> AppSpec:
        if expected_backend_type is not None and not isinstance(
            backend, expected_backend_type
        ):
            raise TypeError(
                f"{type(self).__name__} expected {expected_backend_type.__name__}, got {type(backend).__name__}"
            )
        if history_field_id is not None:
            set_history_enabled = getattr(backend, "set_history_enabled", None)
            if callable(set_history_enabled):
                set_history_enabled(self._uses_field(history_field_id))
        build = getattr(backend, "build_startup_data", None)
        if not callable(build):
            raise TypeError(
                f"{type(backend).__name__} does not provide build_startup_data()"
            )
        return append_bindings_to_app_spec(
            build(),
            panel_bindings=self._bindings_for_compose(),
            controls=self._control_bindings,
            actions=self._actions,
            backend=backend,
        )

    def launch(self):
        """Launch this source directly and return its app handle.

        Prefer `cnv.show()` for normal authoring so all registered sources
        can be integrated.
        """
        from compneurovis._source_runtime import launch_source
        from compneurovis.inline.authoring import _detach_current_source

        _detach_current_source(self)
        return launch_source(self)

    def _make_backend(self) -> BackendBase:
        raise NotImplementedError

    def _build_app_spec_for_backend(self, backend: BackendBase) -> AppSpec:
        # Uniform for every source: compose the raw app-spec, then apply the
        # app-level ``cnv.layout`` grid. No source (generic, neuron, jaxley)
        # special-cases layout -- they only produce panels.
        return apply_panel_grid(
            self._compose_app_spec_for_backend(backend), self._panel_grid
        )

    def _compose_app_spec_for_backend(self, backend: BackendBase) -> AppSpec:
        build = getattr(backend, "build_startup_app_spec", None)
        if not callable(build):
            raise TypeError(
                f"{type(backend).__name__} does not provide build_startup_app_spec()"
            )
        return append_bindings_to_app_spec(
            build(),
            panel_bindings=self._bindings_for_compose(),
            controls=self._control_bindings,
            actions=self._actions,
            backend=backend,
        )

    def _add_series(self, binding: SeriesProducer) -> None:
        binding._register(len(self._series))
        self._series.append(binding)

    def _add_widget_binding(self, binding: Binding) -> None:
        self._widgets.append(binding)

    def _allocate_widget_namespace(self) -> str:
        namespace = f"widget_{self._widget_namespace_index}"
        self._widget_namespace_index += 1
        return namespace

    def _add_control(self, binding: ControlInteraction) -> None:
        binding._register(len(self._control_bindings))
        self._control_bindings.append(binding)

    def _add_action(self, binding: ActionInteraction) -> None:
        binding._register(len(self._actions))
        self._actions.append(binding)

    def _add_click_handler(self, binding: ClickHandlerBinding) -> None:
        self._click_handlers.append(binding)

    def _add_pointer_interaction_handler(
        self, binding: PointerInteractionHandlerBinding
    ) -> None:
        self._pointer_interaction_handlers.append(binding)


class InlineSource(InlineSourceBase):
    """Generic source returned by `cnv.source()`."""

    def __init__(
        self,
        source_like: Callable[[BackendInteractionContext], None]
        | Iterator
        | None = None,
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
            series=self._series,
            controls=self._control_bindings,
            actions=self._actions,
            click_handlers=self._click_handlers,
            pointer_interaction_handlers=self._pointer_interaction_handlers,
            fields=self._fields,
            derived_values=self._derived_values,
            initial_values=self._initial_values,
            step=self._source_like if is_callable else None,
            iterator=iterator,
        )

    def _compose_app_spec_for_backend(self, backend: BackendBase) -> AppSpec:
        del backend
        return _build_inline_app_spec(
            title=self._app_title or self.title,
            controls=self._control_bindings,
            actions=self._actions,
            widgets=self._widgets,
        )


_reserve_widget_names(
    {
        *(name for name in dir(InlineSourceBase) if not name.startswith("_")),
        *(name for name in dir(ControlsRef) if not name.startswith("_")),
        # Public instance attributes are not reported by dir(type), but still
        # win over dynamic attribute dispatch.
        "title",
        "sources",
        "actor_id",
    }
)


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
    return replace(
        app_spec, layout_catalog=LayoutCatalog(layouts=layouts, active=active)
    )


def _build_inline_app_spec(
    *,
    title: str,
    controls: list[ControlInteraction],
    actions: list[ActionInteraction],
    widgets: Sequence[Binding],
) -> AppSpec:
    app_spec = AppSpec(
        data=DataCatalog(),
        view_catalog=ViewCatalog(),
        interactions=InteractionCatalog(),
        layout_catalog=LayoutCatalog.single(LayoutSpec(title=title)),
    )
    return append_bindings_to_app_spec(
        app_spec,
        panel_bindings=widgets,
        controls=controls,
        actions=actions,
    )


__all__ = [
    "InlineSource",
    "InlineSourceBase",
    "apply_panel_grid",
]
