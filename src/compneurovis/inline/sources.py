"""Authoring-layer source adapters for inline mode."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Callable

from compneurovis.backends.base import BackendBase
from compneurovis.core.app_spec import (
    AppSpec,
    DataCatalog,
    InteractionCatalog,
    LayoutCatalog,
    LayoutSpec,
    PanelSpec,
    ViewCatalog,
)
from compneurovis.core.messages import CommandPayload, InvokeAction, Message, MessagePayload, Reset, SetControl, command_message
from compneurovis.inline.backend import InlineBackend, TraceSampler
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
        send: Callable[[CommandPayload], None] | None = None,
    ) -> None:
        self.actor_id = actor_id
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
        # matplotlib-style: creating a source registers it with the current
        # session, so cnv.show() just knows about it (like plt.plot -> plt.show).
        from compneurovis.inline import _register_current_source
        _register_current_source(self)

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
    """Adapter for a callable or iterator source."""

    def __init__(
        self,
        source_like: Callable[[], None] | Callable[[TraceSampler], None] | Iterator,
        *,
        trace_sampler: bool = False,
        title: str = "CompNeuroVis",
    ) -> None:
        super().__init__(title=title)
        if trace_sampler and not callable(source_like):
            raise TypeError("trace_sampler=True only applies to callable sources.")
        self._source_like = source_like
        self._trace_sampler = trace_sampler

    def _make_backend(self) -> InlineBackend:
        is_callable = callable(self._source_like)
        return InlineBackend(
            traces=self._traces,
            controls=self._controls,
            actions=self._actions,
            step=self._source_like if is_callable else None,
            step_uses_trace_sampler=self._trace_sampler,
            iterator=None if is_callable else iter(self._source_like),
        )

    def _build_app_spec_for_backend(self, backend: BackendBase) -> AppSpec:
        del backend
        return _build_inline_app_spec(
            title=self.title,
            traces=self._traces,
            controls=self._controls,
            actions=self._actions,
        )


class ComposedSource(InlineSourceBase):
    """Neutral authoring-layer composition of source declarations.

    No member source is primary. Runtime composition must lower this declaration
    to explicit ActorSpec entries plus RoutingSpec rules; it must not be hidden
    inside one backend actor or borrow another source's backend/AppSpec.
    """

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

    def _build_app_spec_for_backend(self, backend: BackendBase) -> AppSpec:
        del backend
        raise NotImplementedError(
            "ComposedSource AppSpec compilation needs a multi-source runtime compiler. "
            "No source is privileged to provide the composed AppSpec."
        )


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
        data=DataCatalog(fields={trace._field_id: trace._field_spec() for trace in traces}),
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


__all__ = [
    "ComposedSource",
    "InlineSource",
    "InlineSourceBase",
    "RemoteActorRef",
    "RemoteSource",
]
