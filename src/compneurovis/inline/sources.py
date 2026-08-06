"""Authoring-layer source adapters for inline mode."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
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
from compneurovis.backends.interaction import BackendInteractionContext
from compneurovis.core.messages import InvokeAction, MessagePayload, Reset
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
    ActionRef,
    CheckboxRef,
    ControlRef,
    ControlsRef,
    DropdownRef,
    NumberRef,
    PanelRef,
    SliderRef,
    TextRef,
    ValueRef,
    XYPadRef,
)
from compneurovis.inline._ids import slug
from compneurovis.inline.interactions import ActionInteraction, ControlInteraction
from compneurovis.inline.widgets.morphology import MorphologyBinding
from compneurovis.inline.widgets.source_api import SourceWidgetAPI
from compneurovis.inline.widgets.surface import SurfaceBinding

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

    def invoke_action(
        self, action_id: str, payload: dict[str, Any] | None = None
    ) -> None:
        self.command(InvokeAction(action_id, payload or {}))

    def reset(self) -> None:
        self.command(Reset())


class InlineSourceBase(SourceWidgetAPI):
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
        self._panel_bindings: list[Binding] = []
        self._control_bindings: list[ControlInteraction] = []
        self._actions: list[ActionInteraction] = []
        self._controls_panels: dict[str, ControlsRef] = {}
        self._active_controls_panel_id: str | None = None
        self._surfaces: list[SurfaceBinding] = []
        self._fields: list[SnapshotProducer] = []
        self._geometries: list[MorphologyGeometrySpec] = []
        self._derived_values: list[DerivedValueProducer] = []
        self._initial_values: list[tuple[str, Any]] = []
        self._widget_namespace_index = 0
        self._panel_grid: tuple[tuple[str, ...], ...] | None = None
        self._handle = None
        from compneurovis.inline import _register_current_source

        _register_current_source(self)

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
        ref_type: type[ControlRef] = ControlRef,
    ) -> ControlRef:
        binding = ControlInteraction(
            name=name,
            label=label,
            get=get,
            set=set,
            default=default,
            value_spec=value_spec,
            presentation=presentation,
            send_to_backend=send_to_backend,
            panel_id=self._active_controls_panel_id or "controls-panel",
        )
        self._ensure_controls_panel(binding.panel_id)
        self._add_control(binding)
        return ref_type(binding)

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
    ) -> SliderRef:
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
            A slider reference usable in dynamic view properties and value APIs.
        """
        raw = self._initial(default, get, min)
        value_spec = ScalarValueSpec(
            default=round(float(raw)) if int else float(raw),
            min=min,
            max=max,
            value_type="int" if int else "float",
        )
        return self._register_control(
            name,
            label=label,
            get=get,
            set=set,
            value_spec=value_spec,
            presentation=ControlPresentationSpec(
                kind="slider", steps=steps, scale=scale
            ),
            send_to_backend=send_to_backend,
            ref_type=SliderRef,
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
    ) -> NumberRef:
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
            A number-control reference.
        """
        value_spec = ScalarValueSpec(
            default=int(round(float(self._initial(default, get, min)))),
            min=min,
            max=max,
            value_type="int",
        )
        return self._register_control(
            name,
            label=label,
            get=get,
            set=set,
            value_spec=value_spec,
            presentation=ControlPresentationSpec(kind="spinbox"),
            send_to_backend=send_to_backend,
            ref_type=NumberRef,
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
    ) -> DropdownRef:
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
            A dropdown reference usable in dynamic view properties and value APIs.
        """
        opts = tuple(str(option) for option in options)
        value_spec = ChoiceValueSpec(
            default=str(self._initial(default, get, opts[0])), options=opts
        )
        return self._register_control(
            name,
            label=label,
            get=get,
            set=set,
            value_spec=value_spec,
            presentation=ControlPresentationSpec(kind="dropdown"),
            send_to_backend=send_to_backend,
            ref_type=DropdownRef,
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
    ) -> CheckboxRef:
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
            A checkbox reference usable in dynamic view properties and value APIs.
        """
        value_spec = BoolValueSpec(default=bool(self._initial(default, get, False)))
        return self._register_control(
            name,
            label=label,
            get=get,
            set=set,
            value_spec=value_spec,
            presentation=ControlPresentationSpec(kind="checkbox"),
            send_to_backend=send_to_backend,
            ref_type=CheckboxRef,
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
    ) -> TextRef:
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
            A text-control reference.
        """
        value_spec = TextValueSpec(
            default=str(self._initial(default, get, "")),
            placeholder=placeholder,
            max_length=max_length,
        )
        return self._register_control(
            name,
            label=label,
            get=get,
            set=set,
            value_spec=value_spec,
            presentation=ControlPresentationSpec(kind="text"),
            send_to_backend=send_to_backend,
            ref_type=TextRef,
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
    ) -> XYPadRef:
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
            An XY-pad reference usable in dynamic view properties and value APIs.
        """
        x_label, x_min, x_max = x
        y_label, y_min, y_max = y
        resolved = (
            default if default is not None else (get() if get is not None else None)
        )
        if resolved is None:
            resolved = {"x": (x_min + x_max) / 2.0, "y": (y_min + y_max) / 2.0}
        value_spec = XYValueSpec(
            default=dict(resolved),
            x_range=(x_min, x_max),
            y_range=(y_min, y_max),
            x_label=x_label,
            y_label=y_label,
        )
        return self._register_control(
            name,
            label=label,
            get=get,
            set=set,
            value_spec=value_spec,
            send_to_backend=send_to_backend,
            ref_type=XYPadRef,
        )

    def button(
        self,
        name: str,
        *,
        label: str,
        fn: Callable[[BackendInteractionContext], None],
    ) -> ActionRef:
        """Add a button to the controls panel.

        Args:
            name: Stable action name.
            label: User-facing button label.
            fn: Callback invoked as `fn(ctx)` on the backend.

        Returns:
            An action reference that can also be passed to `hotkey()`.

        The context provides value access, status messages, `clear()`, and
        `reset()`.
        """
        binding = ActionInteraction(
            name=name,
            label=label,
            fn=fn,
            panel_id=self._active_controls_panel_id or "controls-panel",
        )
        self._ensure_controls_panel(binding.panel_id)
        self._add_action(binding)
        return ActionRef(binding)

    def hotkey(
        self,
        key: str | Sequence[str],
        target: "ActionRef | Callable[[BackendInteractionContext], None] | None" = None,
        *,
        fn: Callable[[BackendInteractionContext], None] | None = None,
    ) -> ActionRef:
        """Bind a key (or keys) to an effect.

        Args:
            key: Key-sequence string, or a sequence of strings, such as `"r"`,
                `"Escape"`, or `"Ctrl+R"`.
            target: Existing action reference to reuse, or a callback invoked as
                `target(ctx)`.
            fn: Explicit callback alternative to a callable `target`.

        Returns:
            The reused or newly created action reference.
        """
        keys = (key,) if isinstance(key, str) else tuple(key)
        if isinstance(target, ActionRef):
            binding = target._binding
            binding.shortcuts = tuple(binding.shortcuts) + keys
            return target
        handler = target if callable(target) else fn
        if handler is None:
            raise ValueError("hotkey(...) needs a button reference, a callable, or fn=")
        binding = ActionInteraction(
            name=f"hotkey_{'_'.join(keys)}",
            label="",
            fn=handler,
            shortcuts=keys,
            show_button=False,
            panel_id=None,
        )
        self._add_action(binding)
        return ActionRef(binding)

    def create_value(
        self, name: str | ValueRef, *, initial: Any = _MISSING
    ) -> ValueRef:
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
            DerivedValueProducer(
                name=ref.key, fn=fn, max_refresh_hz=max_refresh_hz, initial=initial
            )
        )
        return ref

    def controls(
        self, name: str = "Controls", *, panel_id: str | None = None
    ) -> ControlsRef:
        """Create or return an ordinary controls-panel widget."""
        resolved_id = panel_id or f"{slug(name)}-controls-panel"
        return self._ensure_controls_panel(resolved_id, title=name)

    @property
    def controls_panel(self) -> ControlsRef:
        """Default controls widget; typed source methods delegate to this owner."""
        return self._ensure_controls_panel("controls-panel", title="Controls")

    def _ensure_controls_panel(
        self, panel_id: str, *, title: str = "Controls"
    ) -> ControlsRef:
        current = self._controls_panels.get(panel_id)
        if current is not None:
            return current
        from compneurovis.core.app_spec import PanelSpec

        ref = ControlsRef(panel_id, self)
        self._controls_panels[panel_id] = ref
        self._panel_bindings.append(
            SpecBinding(
                panel=PanelSpec(
                    id=panel_id,
                    kind="controls",
                    title=title,
                )
            )
        )
        return ref

    def _call_in_controls_panel(
        self, panel_id: str, method: str, *args: Any, **kwargs: Any
    ) -> Any:
        if panel_id not in self._controls_panels:
            raise ValueError(f"Unknown controls panel {panel_id!r}")
        previous = self._active_controls_panel_id
        self._active_controls_panel_id = panel_id
        try:
            return getattr(self, method)(*args, **kwargs)
        finally:
            self._active_controls_panel_id = previous

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
            SpecBinding(
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
        selection_id: str,
        selection_initial: Sequence[str] = (),
        selection_multiple: bool = False,
        selectable: bool = True,
        style: Mapping[str, Any] | None = None,
        panel: bool = True,
    ) -> PanelRef:
        if panel:
            self._panel_bindings.append(
                MorphologyBinding(
                    view_id=view_id,
                    panel_id=panel_id,
                    title=title,
                    geometry_id=geometry_id,
                    color_field_id=color_field_id,
                    entity_dim=entity_dim,
                    sample_dim=sample_dim,
                    selection_id=selection_id,
                    selection_initial=tuple(selection_initial),
                    selection_multiple=selection_multiple,
                    selectable=selectable,
                    style={} if style is None else dict(style),
                )
            )
        return PanelRef(panel_id)

    def _panel_bindings_for_compose(self) -> tuple[Binding, ...]:
        # Series producers are not panel bindings: their LineBinding (in
        # ``_widgets``) carries the view/panel and declares the field.
        return (
            *self._widgets,
            *self._panel_bindings,
            *self._surfaces,
        )

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
            panel_bindings=self._panel_bindings_for_compose(),
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
            panel_bindings=self._panel_bindings_for_compose(),
            controls=self._control_bindings,
            actions=self._actions,
            backend=backend,
        )

    def _add_series(self, binding: SeriesProducer) -> None:
        binding._register(len(self._series))
        self._series.append(binding)

    def _add_surface(self, binding: SurfaceBinding) -> None:
        binding._register(len(self._surfaces))
        self._surfaces.append(binding)

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
            surfaces=self._surfaces,
            fields=self._fields,
            derived_values=self._derived_values,
            initial_values=self._initial_values,
            geometries=self._geometries,
            step=self._source_like if is_callable else None,
            iterator=iterator,
        )

    def _compose_app_spec_for_backend(self, backend: BackendBase) -> AppSpec:
        del backend
        return _build_inline_app_spec(
            title=self._app_title or self.title,
            controls=self._control_bindings,
            actions=self._actions,
            surfaces=self._surfaces,
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

    def __init__(
        self, actor_ref: RemoteActorRef, *, title: str = "CompNeuroVis"
    ) -> None:
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
    return replace(
        app_spec, layout_catalog=LayoutCatalog(layouts=layouts, active=active)
    )


def _build_inline_app_spec(
    *,
    title: str,
    controls: list[ControlInteraction],
    actions: list[ActionInteraction],
    surfaces: list[SurfaceBinding],
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
        panel_bindings=(*widgets, *surfaces),
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
