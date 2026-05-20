"""Authoring-layer source adapters for inline mode."""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from typing import Any, Callable

from compneurovis.backends.base import BackendBase
from compneurovis.core.actor import ActorRole
from compneurovis.core.app import (
    AppSpec,
    DataCatalog,
    InteractionCatalog,
    LayoutCatalog,
    LayoutSpec,
    PanelSpec,
    ViewCatalog,
)
from compneurovis.core.messages import CommandPayload, InvokeAction, Message, MessagePayload, Reset, SetControl, command_message
from compneurovis.inline.backend import InlineBackend, SourceStepContext
from compneurovis.inline.bindings import (
    ActionBinding,
    ActionHandle,
    ControlBinding,
    ControlHandle,
    SeriesReaders,
    TraceBinding,
    TraceHandle,
    append_bindings_to_app_spec,
    emit_trace_updates,
)


class RemoteActorRef:
    """Reference to an actor hosted outside the current Python source."""

    def __init__(
        self,
        actor_id: str,
        *,
        role: ActorRole = ActorRole.BACKEND,
        send: Callable[[CommandPayload], None] | None = None,
    ) -> None:
        self.actor_id = actor_id
        self.role = role
        self._send = send

    def command(self, command: CommandPayload) -> None:
        if self._send is not None:
            self._send(command)
            return
        raise NotImplementedError(
            "RemoteActorRef without a send callback requires multi-actor RunSpec "
            "lowering. It cannot be hidden behind a composed backend."
        )

    def set_control(self, control_id: str, value: Any) -> None:
        self.command(SetControl(control_id, value))

    def invoke_action(self, action_id: str, payload: dict[str, Any] | None = None) -> None:
        self.command(InvokeAction(action_id, payload or {}))

    def reset(self) -> None:
        self.command(Reset())


class InlineSourceBase:
    """Base for anything that can participate in the inline authoring mode."""

    def __init__(self, *, title: str = "CompNeuroVis") -> None:
        self.title = title
        self._traces: list[TraceBinding] = []
        self._controls: list[ControlBinding] = []
        self._actions: list[ActionBinding] = []
        self._handle = None

    def trace(self, name: str, *, read: SeriesReaders, x: Callable[[], float], **kwargs) -> TraceHandle:
        binding = TraceBinding(name=name, read=read, x=x, **kwargs)
        self._add_trace(binding)
        return TraceHandle(binding)

    def control(
        self,
        name: str,
        *,
        label: str,
        get: Callable[[], float],
        set: Callable[[Any], None],
        min: float = 0.0,
        max: float = 1.0,
    ) -> ControlHandle:
        binding = ControlBinding(name=name, label=label, get=get, set=set, min=min, max=max)
        self._add_control(binding)
        return ControlHandle(binding)

    def action(
        self,
        name: str,
        *,
        label: str,
        fn: Callable[[], None],
        resets_fields: bool = False,
    ) -> ActionHandle:
        binding = ActionBinding(name=name, label=label, fn=fn, resets_fields=resets_fields)
        self._add_action(binding)
        return ActionHandle(binding)

    def show(self):
        return self.launch()

    def launch(self):
        from compneurovis._source_runtime import launch_source

        return launch_source(self)

    def _make_backend(self) -> BackendBase:
        raise NotImplementedError

    def _notebook_dt(self) -> float:
        backend_dt = getattr(self, "_dt", None)
        return 0.025 if backend_dt is None else float(backend_dt)

    def _build_app_spec_for_backend(self, backend: BackendBase) -> AppSpec:
        build = getattr(backend, "build_startup_app_spec", None)
        if not callable(build):
            raise TypeError(f"{type(backend).__name__} does not provide build_startup_app_spec()")
        return append_bindings_to_app_spec(
            build(),
            traces=self._traces,
            controls=self._controls,
            actions=self._actions,
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
    """Adapter for a callable or iterator-driven pure-Python source."""

    def __init__(self, source_like: Callable[..., None] | Iterator, *, title: str = "CompNeuroVis") -> None:
        super().__init__(title=title)
        self._source_like = source_like

    def _make_backend(self) -> InlineBackend:
        return InlineBackend(
            traces=self._traces,
            controls=self._controls,
            actions=self._actions,
            step=self._step_function(),
        )

    def _build_app_spec_for_backend(self, backend: BackendBase) -> AppSpec:
        del backend
        return _build_inline_app_spec(
            title=self.title,
            traces=self._traces,
            controls=self._controls,
            actions=self._actions,
        )

    def _step_function(self) -> Callable[[SourceStepContext], None] | None:
        if self._source_like is None:
            return None
        if callable(self._source_like):
            if _callable_accepts_step_context(self._source_like):
                return self._source_like

            def step_without_context(_context: SourceStepContext) -> None:
                self._source_like()

            return step_without_context
        iterator = iter(self._source_like)

        def step(_context: SourceStepContext) -> None:
            next(iterator)

        return step


class ComposedSource(InlineSourceBase):
    """Source adapter for controls/actions that coordinate more than one source.

    Composition is an authoring-layer declaration. Runtime composition should
    lower to multiple ActorSpec entries plus RoutingSpec rules; it must not be
    hidden inside one backend actor.
    """

    def __init__(
        self,
        primary: InlineSourceBase,
        *,
        title: str | None = None,
        participants: tuple[Any, ...] = (),
    ) -> None:
        super().__init__(title=title or primary.title)
        self.primary = primary
        self.participants = participants

    def _make_backend(self) -> BackendBase:
        raise NotImplementedError(
            "ComposedSource no longer lowers to a single backend wrapper. "
            "Composition must compile to explicit multi-actor RunSpec topology."
        )

    def _build_app_spec_for_backend(self, backend: BackendBase) -> AppSpec:
        primary_backend = self.primary._make_backend()
        app_spec = self.primary._build_app_spec_for_backend(primary_backend)
        return append_bindings_to_app_spec(
            app_spec,
            traces=self._traces,
            controls=self._controls,
            actions=self._actions,
        )

    def _notebook_dt(self) -> float:
        return self.primary._notebook_dt()


class RemoteSource(InlineSourceBase):
    """Source adapter for an actor hosted outside the current Python process.

    At the authoring layer this is still a source — controls and actions route
    commands to the remote actor; traces declare field subscriptions rather than
    local read lambdas. Compilation to a RunSpec connection slot is not yet
    implemented.
    """

    def __init__(self, actor_ref: RemoteActorRef, *, title: str = "CompNeuroVis") -> None:
        super().__init__(title=title)
        self._actor_ref = actor_ref

    def _make_backend(self) -> BackendBase:
        raise NotImplementedError(
            "RemoteSource does not create a local backend. "
            "Remote source compilation to RunSpec is not yet implemented."
        )

    def _build_app_spec_for_backend(self, backend: BackendBase) -> AppSpec:
        raise NotImplementedError("RemoteSource AppSpec comes from the remote actor.")


def _build_inline_app_spec(
    *,
    title: str,
    traces: list[TraceBinding],
    controls: list[ControlBinding],
    actions: list[ActionBinding],
) -> AppSpec:
    trace_panels = [trace._panel_spec() for trace in traces]
    controls_panel = (
        PanelSpec(
            id="controls-panel",
            kind="controls",
            control_ids=tuple(control._control_id for control in controls),
            action_ids=tuple(action._action_id for action in actions),
        )
        if controls or actions
        else None
    )
    panels = tuple(trace_panels) + ((controls_panel,) if controls_panel else ())

    if controls_panel and trace_panels:
        panel_grid = tuple(
            (panel.id, controls_panel.id) if index == 0 else (panel.id,)
            for index, panel in enumerate(trace_panels)
        )
    elif controls_panel:
        panel_grid = ((controls_panel.id,),)
    else:
        panel_grid = tuple((panel.id,) for panel in trace_panels)

    app_spec = AppSpec(
        data=DataCatalog(fields={trace._field_id: trace._initial_field() for trace in traces}),
        view_catalog=ViewCatalog(views={trace._view_id: trace._view_spec() for trace in traces}),
        interactions=InteractionCatalog(
            controls={control._control_id: control._control_spec() for control in controls},
            actions={action._action_id: action._action_spec() for action in actions},
        ),
        layout_catalog=LayoutCatalog.single(
            LayoutSpec(
                title=title,
                panels=panels,
                panel_grid=panel_grid,
            )
        ),
    )
    return append_bindings_to_app_spec(app_spec, traces=[], controls=[], actions=[])


def _coerce_source(source_like: Any) -> InlineSourceBase:
    if isinstance(source_like, InlineSourceBase):
        return source_like
    if callable(source_like):
        return InlineSource(source_like)
    try:
        iterator = iter(source_like)
    except TypeError as exc:
        raise TypeError(
            "cnv.source(...) expects a callable, an iterator/generator, or a CompNeuroVis adapter."
        ) from exc
    return InlineSource(iterator)


def _callable_accepts_step_context(fn: Callable[..., Any]) -> bool:
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return False

    positional_params = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    required_positional = [
        parameter
        for parameter in positional_params
        if parameter.default is inspect.Parameter.empty
    ]
    required_keyword_only = [
        parameter
        for parameter in signature.parameters.values()
        if parameter.kind == inspect.Parameter.KEYWORD_ONLY and parameter.default is inspect.Parameter.empty
    ]
    accepts_varargs = any(
        parameter.kind == inspect.Parameter.VAR_POSITIONAL
        for parameter in signature.parameters.values()
    )

    if accepts_varargs:
        return True
    if required_keyword_only or len(required_positional) > 1:
        raise TypeError("cnv.source(...) callables must accept either zero arguments or one step context.")
    return len(required_positional) == 1


__all__ = [
    "ComposedSource",
    "InlineSource",
    "InlineSourceBase",
    "RemoteActorRef",
    "RemoteSource",
]
