"""Shared backend-side interaction context.

One uniform construct both the NEURON and Jaxley backends hand to authoring
callbacks (setters, clicks, keys, actions). It is the sim-side half of the
interaction vocabulary; the render-side half is
``frontends.vispy.interaction_context.FrontendInteractionContext``. The two are
deliberately *not* merged: same vocabulary, opposite substrate (sim model vs Qt
window) and opposite process. ``set_value`` here writes backend UI state and
emits an update *to* the frontend; the frontend's writes drive a local re-render.

Backend-specific optimizations (NEURON PtrVector refs, Jaxley runtime parameter
refresh, etc.) are not part of this context -- they live on the concrete backends
and their source bindings, untouched by this shared surface.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

import numpy as np

from compneurovis.core.messages import BindingValuePatch, Status

SELECTED_ENTITY_ID_KEY = "selected_entity_id"
SELECTED_ENTITY_IDS_KEY = "_selected"


def _value_key(value: Any) -> str:
    return str(getattr(value, "key", value))


def _is_selection_ref(value: Any) -> bool:
    return bool(getattr(value, "_is_selection_ref", False))


def _selection_ids_from_internal(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [str(value)]
    try:
        values = list(value)
    except TypeError:
        return [str(value)]
    return [str(item) for item in values]


def _selection_to_internal(value: Any, *, select_multiple: bool) -> list[str]:
    if value is None:
        return []
    if select_multiple:
        if isinstance(value, (str, bytes)):
            raise ValueError("morphology(select_multiple=True, selected=...) expects an iterable of entity ids, not a string")
        try:
            values = list(value)
        except TypeError as exc:
            raise TypeError("morphology(select_multiple=True, selected=...) expects an iterable of entity ids") from exc
        return [str(item) for item in values]
    if isinstance(value, (list, tuple, set, np.ndarray)):
        values = list(value)
        if not values:
            return []
        raise ValueError("morphology(selected=...) expects a single entity id unless select_multiple=True")
    return [str(value)]


def _selection_from_internal(value: Any, *, select_multiple: bool) -> Any:
    selected = _selection_ids_from_internal(value)
    if select_multiple:
        return selected
    return selected[0] if selected else None


@runtime_checkable
class InteractionBackend(Protocol):
    """Minimal backend surface the interaction context talks to.

    Any backend exposing these members gets the shared context for free. Members
    beyond this (model handles, samplers, ref optimizations) stay backend-local.
    """

    _ui_state: dict[str, Any]
    geometry: Any

    def emit_update(self, payload: Any) -> None: ...

    def control_values(self) -> dict[str, Any]: ...

    def _dispatch_action(self, action_id: str, payload: dict[str, Any]) -> bool: ...


class BackendInteractionContext:
    """Sim-side interaction context shared by every backend source."""

    def __init__(self, backend: InteractionBackend):
        self.backend = backend

    def set_value(self, key: Any, value: Any) -> None:
        resolved_key = _value_key(key)
        if _is_selection_ref(key):
            value = _selection_to_internal(value, select_multiple=bool(getattr(key, "select_multiple", False)))
        self.backend._ui_state[resolved_key] = value
        self.backend.emit_update(BindingValuePatch({resolved_key: value}))

    def get_value(self, key: Any, default: Any = None) -> Any:
        if _is_selection_ref(key):
            raw = self.backend._ui_state.get(key.key, None)
            if raw is None:
                return default
            return _selection_from_internal(raw, select_multiple=bool(getattr(key, "select_multiple", False)))
        return self.backend._ui_state.get(_value_key(key), default)

    def controls(self) -> dict[str, Any]:
        return self.backend.control_values()

    @property
    def selected_entity_id(self) -> str | None:
        value = self.backend._ui_state.get(SELECTED_ENTITY_ID_KEY)
        return str(value) if value is not None else None

    def entity_info(self, entity_id: str | None = None) -> dict[str, Any] | None:
        current_id = entity_id or self.selected_entity_id
        if current_id is None or self.backend.geometry is None:
            return None
        try:
            return self.backend.geometry.entity_info(current_id)
        except KeyError:
            return None

    def show_status(self, message: str, timeout_ms: int | None = None) -> None:
        self.backend.emit_update(Status(message, timeout_ms))

    def clear_status(self) -> None:
        self.backend.emit_update(Status("", 0))

    def invoke_action(self, action_id: str, payload: dict[str, Any] | None = None) -> None:
        self.backend._dispatch_action(action_id, payload or {})

    @property
    def trace_sampler(self) -> Any:
        """Pull-sampler over the source's declared traces.

        Always present (one uniform ctx, no per-callback variants). Most useful
        inside a user-driven step fn to sample at sim resolution; harmless
        elsewhere. ``None`` only for backends that declare no traces.
        """
        return getattr(self.backend, "_trace_sampler", None)


__all__ = [
    "BackendInteractionContext",
    "InteractionBackend",
    "SELECTED_ENTITY_ID_KEY",
    "SELECTED_ENTITY_IDS_KEY",
    "_is_selection_ref",
    "_selection_from_internal",
    "_selection_ids_from_internal",
    "_selection_to_internal",
    "_value_key",
]
