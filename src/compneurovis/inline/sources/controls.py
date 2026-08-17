"""Typed control, action, and frontend-value authoring for sources."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Callable

from compneurovis.backends.interaction import BackendInteractionContext
from compneurovis.core.controls import ControlPresentationSpec, ControlValueSpec
from compneurovis.inline._ids import slug
from compneurovis.inline.control_registry import (
    ControlAuthoringContext,
    control_factory,
)
from compneurovis.inline.compiler import SpecBinding
from compneurovis.inline.data_producers import DerivedValueProducer
from compneurovis.inline.interactions import (
    ControlInteraction,
    KeyBindingInteraction,
)
from compneurovis.inline.refs import (
    ButtonRef,
    CheckboxRef,
    ControlRef,
    ControlsRef,
    DropdownRef,
    HotkeyRef,
    NumberRef,
    SliderRef,
    TextRef,
    ValueRef,
    XYPadRef,
)

_MISSING = object()


class SourceControls:
    """Mixin implementing the explicit typed source control surface."""

    def _register_control(
        self,
        name: str,
        *,
        label: str,
        get: Callable[[], Any] | None = None,
        set: Callable[[BackendInteractionContext, Any], None] | None = None,
        fn: Callable[[BackendInteractionContext], None] | None = None,
        default: Any = 0.0,
        value_spec: ControlValueSpec,
        presentation: ControlPresentationSpec | None = None,
        send_to_backend: bool | None = None,
        visible: bool = True,
        ref_type: type[ControlRef] = ControlRef,
        panel_id: str | None = None,
    ) -> ControlRef:
        binding = ControlInteraction(
            name=name,
            label=label,
            get=get,
            set=set,
            fn=fn,
            value_spec=value_spec,
            presentation=presentation,
            send_to_backend=send_to_backend,
            visible=visible,
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
        context = ControlAuthoringContext(self, panel_id)
        result = control_factory(kind)(context, *args, **kwargs)
        if not isinstance(result, ControlRef):
            raise TypeError(
                f"Control authoring factory {kind!r} must return ControlRef, "
                f"got {type(result).__name__}"
            )
        return result

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
        visible: bool = True,
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
            visible: Initial visibility. Change `control.visible` at runtime.

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
            visible=visible,
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
        visible: bool = True,
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
            visible: Initial visibility. Change `control.visible` at runtime.

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
            visible=visible,
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
        visible: bool = True,
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
            visible: Initial visibility. Change `control.visible` at runtime.

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
            visible=visible,
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
        visible: bool = True,
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
            visible: Initial visibility. Change `control.visible` at runtime.

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
            visible=visible,
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
        visible: bool = True,
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
            visible: Initial visibility. Change `control.visible` at runtime.

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
            visible=visible,
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
        visible: bool = True,
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
            visible: Initial visibility. Change `control.visible` at runtime.

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
            visible=visible,
        )

    def button(
        self,
        name: str,
        *,
        label: str,
        fn: Callable[[BackendInteractionContext], None] | None = None,
        hotkey: HotkeyRef | None = None,
    ) -> ButtonRef:
        """Add a button to the controls panel.

        Args:
            name: Stable action name.
            label: User-facing button label.
            fn: Callback invoked as `fn(ctx)` on the backend. Omit when
                consuming an existing `hotkey` action.
            hotkey: Existing keyboard action whose callback this button reuses.

        Returns:
            An action reference that can also be passed to `hotkey()`.

        The context provides value access, status messages, `clear()`, and
        `reset()`.
        """
        return self._invoke_control_factory(
            self._active_controls_panel_id or "controls-panel",
            "button",
            name,
            label=label,
            fn=fn,
            hotkey=hotkey,
        )

    def hotkey(
        self,
        key: str | Sequence[str],
        target: "ControlRef | Callable[[BackendInteractionContext], None] | None" = None,
        *,
        fn: Callable[[BackendInteractionContext], None] | None = None,
    ) -> HotkeyRef:
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
        handler = fn
        target_control = None
        if target is not None:
            binding = getattr(target, "_binding", None)
            if isinstance(binding, ControlInteraction):
                if fn is not None:
                    raise ValueError(
                        "hotkey(...) targeting a control reuses its effect; omit fn"
                    )
                target_control = binding
            elif callable(target):
                if fn is not None:
                    raise ValueError("hotkey(...) takes a callable target or fn, not both")
                handler = target
            else:
                raise TypeError(
                    "hotkey(...) expects a control reference or a callable, "
                    f"got {type(target).__name__}"
                )
        if target_control is None and handler is None:
            raise ValueError("hotkey(...) needs a control reference, a callable, or fn=")
        binding = KeyBindingInteraction(
            name=f"hotkey_{'_'.join(keys)}",
            shortcuts=keys,
            fn=handler,
            target=target_control,
        )
        self._add_key_binding(binding)
        return HotkeyRef(binding)

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
        self,
        name: str = "Controls",
        *,
        panel_id: str | None = None,
        panel_kind: str = "controls",
    ) -> ControlsRef:
        """Create or return a placeable controls widget.

        `panel_kind` selects any frontend-local registered panel host. The
        default uses CompNeuroVis's standard controls host.
        """
        resolved_id = panel_id or f"{slug(name)}-controls-panel"
        return self._ensure_controls_panel(
            resolved_id,
            title=name,
            panel_kind=panel_kind,
        )

    @property
    def controls_panel(self) -> ControlsRef:
        """Default controls widget; typed source methods delegate to this owner."""
        return self._ensure_controls_panel(
            "controls-panel",
            title="Controls",
            panel_kind="controls",
        )

    def _ensure_controls_panel(
        self,
        panel_id: str,
        *,
        title: str = "Controls",
        panel_kind: str | None = None,
    ) -> ControlsRef:
        current = self._controls_panels.get(panel_id)
        if current is not None:
            if (
                panel_kind is not None
                and self._controls_panel_kinds[panel_id] != panel_kind
            ):
                raise ValueError(
                    f"Controls panel {panel_id!r} is already declared with kind "
                    f"{self._controls_panel_kinds[panel_id]!r}, not {panel_kind!r}"
                )
            return current
        from compneurovis.core.app_spec import PanelSpec

        resolved_kind = "controls" if panel_kind is None else str(panel_kind).strip()
        if not resolved_kind:
            raise ValueError("Controls panel kind must be a non-empty string")
        ref = ControlsRef(panel_id, self)
        self._controls_panels[panel_id] = ref
        self._controls_panel_kinds[panel_id] = resolved_kind
        self._widgets.append(
            SpecBinding(
                panel=PanelSpec(
                    id=panel_id,
                    kind=resolved_kind,
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
