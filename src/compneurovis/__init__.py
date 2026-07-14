"""Public authoring surface for CompNeuroVis."""

from __future__ import annotations

from importlib import import_module

from compneurovis.backends import BackendBase, HistoryCaptureMode
from compneurovis.inline import layout, show, source
from compneurovis.core import (
    ActionSpec,
    ActorBase,
    ActorSpec,
    AppRuntime,
    AppProjection,
    AppFragmentSpec,
    AppRef,
    app_ref,
    AppSpec,
    DEFAULT_FRAGMENT_ID,
    AppFragment,
    BoolValueSpec,
    Channel,
    ChoiceValueSpec,
    ControlPresentationSpec,
    ControlSpec,
    DataCatalog,
    DiagnosticsSpec,
    Field,
    GeometrySpec,
    GridGeometrySpec,
    GridSliceOperatorSpec,
    IdentifiedSpec,
    InteractionCatalog,
    BarPlotViewSpec,
    LayoutCatalog,
    LayoutSpec,
    LevelMarker,
    LinePlotViewSpec,
    MessageMatch,
    StateGraphViewSpec,
    MorphologyGeometrySpec,
    MorphologyViewSpec,
    OperatorSpec,
    PanelSpec,
    RouteSpec,
    RoutingSpec,
    RunSpec,
    ScalarValueSpec,
    SpecBase,
    ValueBindingSpec,
    TextValueSpec,
    SurfaceViewSpec,
    ViewSpec,
    ViewCatalog,
    XYValueSpec,
    build_default_layout,
    build_default_layout_catalog,
    default_panel_grid,
)
from compneurovis.frontends import FrontendBase
from compneurovis.core.run import run_actor, run_app, run_orchestrator, start_app
from compneurovis.core.actor_launchers import ScriptActorProcess, ThreadActorLauncher, get_script_actor_channel
from compneurovis.core.app_handle import AppHandle
from compneurovis.core.messages import (
    CommandMessage,
    CameraCommand,
    Message,
    MessagePayload,
    MessageType,
    RenderedFrame,
    UpdateMessage,
    command_message,
    make_message,
    message_type_for_payload,
    update_message,
)
from compneurovis.core.bus import Bus, BusFabric, BusRoutingError, BusThread, bus_transport
from compneurovis.transports import PipeEndpoint, Transport, inprocess_transport, pipe_transport

__all__ = [
    "ActionSpec",
    "ActorBase",
    "ActorSpec",
    "AppRuntime",
    "AppFragmentSpec",
    "AppRef",
    "app_ref",
    "AppProjection",
    "AppSpec",
    "AppFragment",
    "BackendBase",
    "BoolValueSpec",
    "Channel",
    "Bus",
    "BusFabric",
    "BusRoutingError",
    "BusThread",
    "bus_transport",
    "build_default_layout",
    "build_default_layout_catalog",
    "ChoiceValueSpec",
    "CommandMessage",
    "CameraCommand",
    "ControlPresentationSpec",
    "ControlSpec",
    "DataCatalog",
    "DiagnosticsSpec",
    "default_panel_grid",
    "DEFAULT_FRAGMENT_ID",
    "Field",
    "FrontendBase",
    "GeometrySpec",
    "GridGeometrySpec",
    "GridSliceOperatorSpec",
    "HistoryCaptureMode",
    "IdentifiedSpec",
    "InteractionCatalog",
    "layout",
    "show",
    "source",
    "experimental",
    "jaxley",
    "neuron",
    "LayoutCatalog",
    "LayoutSpec",
    "BarPlotViewSpec",
    "LevelMarker",
    "LinePlotViewSpec",
    "Message",
    "MessagePayload",
    "MessageType",
    "RenderedFrame",
    "MessageMatch",
    "MorphologyGeometrySpec",
    "MorphologyViewSpec",
    "OperatorSpec",
    "PanelSpec",
    "PipeEndpoint",
    "inprocess_transport",
    "RouteSpec",
    "RoutingSpec",
    "RunSpec",
    "ScalarValueSpec",
    "SpecBase",
    "ValueBindingSpec",
    "StateGraphViewSpec",
    "SurfaceViewSpec",
    "TextValueSpec",
    "Transport",
    "UpdateMessage",
    "ViewCatalog",
    "ViewSpec",
    "VispyActorHost",
    "VispyFrontendWindow",
    "XYValueSpec",
    "command_message",
    "make_message",
    "message_type_for_payload",
    "pipe_transport",
    "AppHandle",
    "ScriptActorProcess",
    "ThreadActorLauncher",
    "get_script_actor_channel",
    "run_actor",
    "run_app",
    "run_orchestrator",
    "start_app",
    "update_message",
    "NeuronBackend",
    "NeuronSource",
    "JaxleyBackend",
    "JaxleySource",
]

_OPTIONAL_EXPORTS = {
    "NeuronBackend": ("compneurovis.backends.neuron", "NeuronBackend", "neuron"),
    "NeuronSource": ("compneurovis.backends.neuron", "NeuronSource", "neuron"),
    "JaxleyBackend": ("compneurovis.backends.jaxley", "JaxleyBackend", "jaxley"),
    "JaxleySource": ("compneurovis.backends.jaxley", "JaxleySource", "jaxley"),
    "VispyActorHost": ("compneurovis.frontends.vispy", "VispyActorHost", None),
    "VispyFrontendWindow": ("compneurovis.frontends.vispy", "VispyFrontendWindow", None),
}

_OPTIONAL_MODULES = {
    "experimental": "compneurovis.experimental",
    "neuron": "compneurovis.neuron",
    "jaxley": "compneurovis.jaxley",
}


def __getattr__(name: str):
    module_name = _OPTIONAL_MODULES.get(name)
    if module_name is not None:
        module = import_module(module_name)
        globals()[name] = module
        return module

    target = _OPTIONAL_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name, extra_name = target
    try:
        module = import_module(module_name)
    except ModuleNotFoundError as exc:
        if extra_name is None:
            raise ModuleNotFoundError(
                f"CompNeuroVis export {name!r} requires desktop dependencies from "
                "the base package. Reinstall CompNeuroVis to restore them."
            ) from exc
        raise ModuleNotFoundError(
            f"Optional CompNeuroVis export {name!r} requires extra {extra_name!r}. "
            f'Install it with `pip install -e ".[{extra_name}]"`.'
        ) from exc

    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
