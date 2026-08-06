"""Shared backend-side interaction context.

One uniform construct both the NEURON and Jaxley backends hand to authoring
callbacks (setters, clicks, keys, actions). It is the sim-side half of the
interaction vocabulary; the render-side half is
``frontends.vispy.interaction_context.FrontendInteractionContext``. The two are
deliberately *not* merged: same vocabulary, opposite substrate (sim model vs Qt
window) and opposite process. ``set_value`` here writes backend values and
emits an update *to* the frontend; the frontend's writes drive a local re-render.

Backend-specific optimizations (NEURON PtrVector refs, Jaxley runtime parameter
refresh, etc.) are not part of this context -- they live on the concrete backends
and their source bindings, untouched by this shared surface.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

import numpy as np

from compneurovis.core.messages import Reset, Status, ValueChange, command_message


def _value_key(value: Any) -> str:
    return str(
        getattr(value, "id", value)
        if _is_selection_ref(value)
        else getattr(value, "key", value)
    )


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
            raise ValueError(
                "select_multiple=True selection expects an iterable of entity ids, "
                "not a string"
            )
        try:
            values = list(value)
        except TypeError as exc:
            raise TypeError(
                "select_multiple=True selection expects an iterable of entity ids"
            ) from exc
        return [str(item) for item in values]
    if isinstance(value, (list, tuple, set, np.ndarray)):
        values = list(value)
        if not values:
            return []
        raise ValueError(
            "single selection expects one entity id unless select_multiple=True"
        )
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

    values: Any
    geometry: Any

    def emit_update(self, payload: Any) -> None: ...

    def reset_field_history(self, field_ids: set[str] | None = None) -> None: ...

    def handle(self, message: Any) -> None: ...

    def _dispatch_action(self, action_id: str, payload: dict[str, Any]) -> bool: ...


class BackendInteractionContext:
    """Context passed to source callbacks on the simulation side.

    Control setters receive `set(ctx, value)`. Buttons and hotkeys receive
    `fn(ctx)`. The context coordinates values, selection, plot history,
    reset behavior, and status messages without exposing transport details.
    """

    def __init__(self, backend: InteractionBackend):
        self.backend = backend

    def set_value(self, key: Any, value: Any) -> None:
        """Set one runtime value and publish the change.

        Args:
            key: Control handle, value reference, selection reference, or name.
            value: New value.
        """
        self.set_values({key: value})

    def set_values(self, updates: Mapping[Any, Any]) -> None:
        """Write several values and publish them as one ``ValueChange``.

        Args:
            updates: Mapping from control/value/selection references or names to
                their new values.

        ``ValueChange`` carries a mapping, so a bulk write (e.g. resyncing every
        control after a preset load) is one message, not one per key.
        """
        resolved: dict[str, Any] = {}
        for key, value in updates.items():
            if _is_selection_ref(key):
                value = _selection_to_internal(value, select_multiple=key.multiple)
            resolved_key = _value_key(key)
            self.backend.values.set(resolved_key, value)
            resolved[resolved_key] = value
        if resolved:
            self.backend.emit_update(ValueChange(resolved))

    def get_value(self, key: Any, default: Any = None) -> Any:
        """Read one runtime value.

        Args:
            key: Control handle, value reference, selection reference, or name.
            default: Value returned when the key is unset.

        Returns:
            Current runtime value or `default`.
        """
        if _is_selection_ref(key):
            raw = self.backend.values.get(key.id, None)
            if raw is None:
                return default
            return _selection_from_internal(raw, select_multiple=key.multiple)
        return self.backend.values.get(_value_key(key), default)

    def controls(self) -> dict[str, Any]:
        """Current value of each declared control, re-reading its ``get=``.

        Only bound controls -- not every value the backend happens to store
        (selection ids, entity labels, derived values), which are not controls
        and must not be echoed back as if they were.
        """
        values = self.backend.values
        return {key: values.get(key) for key in values.bound_keys()}

    @property
    def selected_entity_id(self) -> str | None:
        """Most recently selected entity in the backend's active selection."""
        selection_id = getattr(self.backend, "selection_id", lambda: None)()
        if selection_id is None:
            return None
        selected = _selection_ids_from_internal(self.backend.values.get(selection_id))
        return selected[-1] if selected else None

    def entity_info(self, entity_id: str | None = None) -> dict[str, Any] | None:
        """Return metadata for an entity.

        Args:
            entity_id: Entity to inspect. Defaults to current selection.

        Returns:
            Entity metadata, or `None` when unavailable.
        """
        current_id = entity_id or self.selected_entity_id
        if current_id is None or self.backend.geometry is None:
            return None
        try:
            return self.backend.geometry.entity_info(current_id)
        except KeyError:
            return None

    def clear(self, *handles: Any) -> None:
        """Clear the scrolling history of plots.

        Args:
            *handles: Line handles to clear. Omit them to clear all histories.

        ``ctx.clear()`` clears every plot; ``ctx.clear(volt, gates)`` clears only
        the given handles (the ones ``source.line(...)`` returned). No "fields"
        concept leaks to the author -- you name the plots you made, or none for all.
        """
        if handles:
            field_ids: set | None = {
                fid
                for handle in handles
                if (
                    fid := getattr(handle, "field_id", None)
                    or getattr(handle, "_field_id", None)
                )
            }
        else:
            field_ids = None
        self.backend.reset_field_history(field_ids)

    def reset(self) -> None:
        """Run the backend's full reset path.

        Simulator backends reset their model and output histories. For plain
        Python sources that own an external model object, reset that model in
        the action first, then call ``ctx.reset()`` to reset the stream/history
        boundary.
        """
        self.backend.handle(command_message(Reset()))

    def show_status(self, message: str, timeout_ms: int | None = None) -> None:
        """Show a frontend status message.

        Args:
            message: Text to display.
            timeout_ms: Optional automatic-clear delay in milliseconds.
        """
        self.backend.emit_update(Status(message, timeout_ms))

    def clear_status(self) -> None:
        """Clear the current frontend status message."""
        self.backend.emit_update(Status("", 0))

    def invoke_action(
        self, action_id: str, payload: dict[str, Any] | None = None
    ) -> None:
        """Invoke another registered action by its internal action id."""
        self.backend._dispatch_action(action_id, payload or {})

    @property
    def series_sampler(self) -> Any:
        """Pull-sampler over the source's declared series.

        Always present (one uniform ctx, no per-callback variants). Most useful
        inside a user-driven step fn to sample at sim resolution; harmless
        elsewhere. ``None`` only for backends that declare no series.
        """
        return getattr(self.backend, "_series_sampler", None)


__all__ = [
    "BackendInteractionContext",
    "InteractionBackend",
    "_is_selection_ref",
    "_selection_from_internal",
    "_selection_ids_from_internal",
    "_selection_to_internal",
    "_value_key",
]
