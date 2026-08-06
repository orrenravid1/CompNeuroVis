"""Typed control, action, and frontend-value authoring for sources."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Callable

from compneurovis.backends.interaction import BackendInteractionContext
from compneurovis.core.controls import ControlPresentationSpec, ControlValueSpec
from compneurovis.inline._ids import slug
from compneurovis.inline.builtin_controls import register_builtin_controls
from compneurovis.inline.control_registry import (
    ControlAuthoringContext,
    control_factory,
)
from compneurovis.inline.compiler import SpecBinding
from compneurovis.inline.data_producers import DerivedValueProducer
from compneurovis.inline.interactions import ActionInteraction, ControlInteraction
from compneurovis.inline.refs import (
    ActionRef,
    CheckboxRef,
    ControlRef,
    ControlsRef,
    DropdownRef,
    NumberRef,
    SliderRef,
    TextRef,
    ValueRef,
    XYPadRef,
)

_MISSING = object()
register_builtin_controls()


class SourceControls:
    """Mixin implementing the explicit typed source control surface."""

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
        panel_id: str | None = None,
    ) -> ControlRef:
        binding = ControlInteraction(
            name=name,
            label=label,
            get=get,
            set=set,
            value_spec=value_spec,
            presentation=presentation,
            send_to_backend=send_to_backend,
            panel_id=panel_id or self._active_controls_panel_id or "controls-panel",
        )
        self._ensure_controls_panel(binding.panel_id)
        self._add_control(binding)
        return ref_type(binding)

    def _invoke_control_factory(
        self,
        panel_id: str,
        kind: str,
        *args: Any,
        **kwargs: Any,
    ) -> ControlRef:
        self._ensure_controls_panel(panel_id)
        context = ControlAuthoringContext(self, panel_id)
        return control_factory(kind)(context, *args, **kwargs)

    # -- typed control calls -------------------------------------------------
    # One call per widget kind, mirroring matplotlib widgets / Streamlit. Each
    # typed call chooses the value spec and presentation directly; there is no
    # generic source-level escape hatch for arbitrary control specs.

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
        return self._invoke_control_factory(
            "controls-panel",
            "slider",
            name,
            label=label,
            min=min,
            max=max,
            get=get,
            set=set,
            default=default,
            steps=steps,
            scale=scale,
            int=int,
            send_to_backend=send_to_backend,
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
        return self._invoke_control_factory(
            "controls-panel",
            "number",
            name,
            label=label,
            min=min,
            max=max,
            get=get,
            set=set,
            default=default,
            send_to_backend=send_to_backend,
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
        return self._invoke_control_factory(
            "controls-panel",
            "dropdown",
            name,
            label=label,
            options=options,
            get=get,
            set=set,
            default=default,
            send_to_backend=send_to_backend,
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
        return self._invoke_control_factory(
            "controls-panel",
            "checkbox",
            name,
            label=label,
            get=get,
            set=set,
            default=default,
            send_to_backend=send_to_backend,
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
        return self._invoke_control_factory(
            "controls-panel",
            "text",
            name,
            label=label,
            get=get,
            set=set,
            default=default,
            placeholder=placeholder,
            max_length=max_length,
            send_to_backend=send_to_backend,
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
        return self._invoke_control_factory(
            "controls-panel",
            "xy_pad",
            name,
            label=label,
            x=x,
            y=y,
            get=get,
            set=set,
            default=default,
            send_to_backend=send_to_backend,
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
        self._widgets.append(
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



__all__ = ["SourceControls"]
