"""Shared backend-side interaction context.

One uniform construct every backend hands to source callbacks (setters, clicks,
pointer tools, keys, and actions). Application mutation is backend-authoritative;
frontends own native focus, capture, hit testing, and fallback presentation but
do not expose a parallel model-mutation context. ``set_value`` writes backend
state and emits its canonical update to whichever frontends are routed to it.

Backend-specific optimizations (NEURON PtrVector refs, Jaxley runtime parameter
refresh, etc.) are not part of this context -- they live on the concrete backends
and their source bindings, untouched by this shared surface.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

import numpy as np

from compneurovis.core.messages import (
    FieldReplace,
    Reset,
    Status,
    ValueChange,
    command_message,
)


def _value_key(value: Any) -> str:
    if _is_selection_ref(value):
        return str(value.id)
    return str(getattr(value, "value_key", getattr(value, "key", value)))


def _is_selection_ref(value: Any) -> bool:
    return bool(getattr(value, "_is_selection_ref", False))


def _selection_values_from_internal(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [value]
    try:
        values = list(value)
    except TypeError:
        return [value]
    return values


def _selection_ids_from_internal(value: Any) -> list[str]:
    """Entity-selection convenience layered on neutral selection values."""

    return [str(item) for item in _selection_values_from_internal(value)]


def _selection_to_internal(
    value: Any,
    *,
    select_multiple: bool,
    item_kind: str,
) -> list[Any]:
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
        return [str(item) for item in values] if item_kind == "entity" else values
    if isinstance(value, (list, tuple, set, np.ndarray)):
        values = list(value)
        if not values:
            return []
        raise ValueError(
            "single selection expects one entity id unless select_multiple=True"
        )
    return [str(value) if item_kind == "entity" else value]


def _selection_from_internal(value: Any, *, select_multiple: bool) -> Any:
    selected = _selection_values_from_internal(value)
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

    def _dispatch_invoke(self, interaction_id: str, payload: dict[str, Any]) -> bool: ...


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
                value = _selection_to_internal(
                    value,
                    select_multiple=key.multiple,
                    item_kind=key.item_kind,
                )
            resolved_key = _value_key(key)
            resolved[resolved_key] = value
        publish = getattr(self.backend, "_publish_value_updates", None)
        if callable(publish):
            publish(resolved)
            return
        for key, value in resolved.items():
            self.backend.values.set(key, value)
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

    def set_data(
        self,
        target: Any,
        values: Any,
        *,
        coords: Mapping[str, Any] | None = None,
    ) -> None:
        """Replace snapshot data displayed by a data-backed widget.

        ``read=`` fields remain continuously sampled. ``values=`` fields can be
        replaced explicitly with ``ctx.set_data(surface, values)`` when an
        application event loads a new snapshot. Supplying ``coords`` atomically
        replaces coordinates with the values, allowing dimensions such as a
        marker or annotation collection to change length.
        """
        field_id = getattr(target, "field_id", None) or getattr(
            target, "_field_id", None
        )
        if not field_id:
            raise TypeError("set_data() target must be a data-backed widget reference")
        array = np.asarray(values, dtype=np.float32)
        replace = getattr(self.backend, "replace_field_data", None)
        if callable(replace) and replace(
            str(field_id), array, coords=coords
        ):
            return
        self.backend.emit_update(
            FieldReplace(
                field_id=str(field_id),
                values=array,
                coords=None if coords is None else dict(coords),
            )
        )

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
        selection = getattr(self.backend, "_selection_specs", {}).get(selection_id)
        if selection is None or selection.item_kind != "entity":
            return None
        selected = _selection_ids_from_internal(self.backend.values.get(selection_id))
        return selected[-1] if selected else None

    @property
    def click_id(self) -> str | None:
        """Authored click interaction currently being handled, if any."""
        return getattr(self.backend, "click_id", lambda: None)()

    @property
    def click_value(self) -> Any:
        """Resolved data-only value of the click currently being handled."""
        return getattr(self.backend, "click_value", lambda: None)()

    @property
    def click_gesture(self) -> Any:
        """Neutral press/release gesture currently being handled."""
        return getattr(self.backend, "click_gesture", lambda: None)()

    @property
    def entity_click_id(self) -> str | None:
        """Current click id when its declared result kind is ``entity``."""
        return getattr(self.backend, "entity_click_id", lambda: None)()

    @property
    def hit_target_id(self) -> str | None:
        """Exact authored hit target currently being handled, if any."""
        return getattr(self.backend, "hit_target_id", lambda: None)()

    def entity_info(
        self,
        entity_id: str | None = None,
        *,
        selection: Any = None,
    ) -> dict[str, Any] | None:
        """Return metadata for an entity.

        Args:
            entity_id: Entity to inspect. Defaults to current selection.

        Returns:
            Entity metadata, or `None` when unavailable.
        """
        current_id = entity_id or self.selected_entity_id
        if current_id is None:
            return None
        if selection is not None:
            selection_id = _value_key(selection)
        elif self.hit_target_id is not None:
            # Click and pointer handlers retain their exact target. A click may
            # explicitly couple it to selection; a pointer never inherits an
            # unrelated sole-selection fallback.
            selection_id = getattr(self.backend, "_active_selection_id", None)
        else:
            selection_id = getattr(self.backend, "selection_id", lambda: None)()
        resolver = getattr(self.backend, "entity_info", None)
        if callable(resolver):
            return resolver(current_id, selection_id=selection_id)
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

    def invoke(
        self, interaction_id: str, payload: dict[str, Any] | None = None
    ) -> None:
        """Activate another invocable interaction by its canonical id."""
        self.backend._dispatch_invoke(interaction_id, payload or {})

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
