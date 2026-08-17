"""Frontend-local registries for notebook control and action presentations."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from compneurovis.core.controls import ControlSpec


@dataclass(frozen=True, slots=True, weakref_slot=True)
class NotebookControlRenderContext:
    """Host-independent value emission service for one notebook control."""

    _emit_value: Callable[[Any], None] = field(repr=False)

    def emit(self, value: Any) -> None:
        self._emit_value(value)


@dataclass(frozen=True, slots=True)
class NotebookControlPresentation:
    """Rendered ipywidget plus the frontend-driven value synchronization hook."""

    widget: Any
    _set_value: Callable[[Any], None] = field(repr=False)

    def set_value(self, value: Any) -> None:
        self._set_value(value)


NotebookControlRenderer = Callable[
    [NotebookControlRenderContext, ControlSpec, Any],
    NotebookControlPresentation,
]


@dataclass(frozen=True, slots=True)
class NotebookFramePolicy:
    """Requested notebook service level for one rasterized view kind."""

    target_hz: float = 8.0
    priority: int = 0
    max_inflight: int = 1
    raster_scale: float = 1.0
    jpeg_quality: int = 75

    def __post_init__(self) -> None:
        target_hz = float(self.target_hz)
        if target_hz <= 0.0:
            raise ValueError("Notebook frame-policy target_hz must be positive")
        object.__setattr__(self, "target_hz", target_hz)
        object.__setattr__(self, "priority", int(self.priority))
        max_inflight = int(self.max_inflight)
        if max_inflight <= 0:
            raise ValueError("Notebook frame-policy max_inflight must be positive")
        object.__setattr__(self, "max_inflight", max_inflight)
        raster_scale = float(self.raster_scale)
        if raster_scale < 1.0:
            raise ValueError("Notebook frame-policy raster_scale cannot be below 1")
        object.__setattr__(self, "raster_scale", raster_scale)
        jpeg_quality = int(self.jpeg_quality)
        if not 1 <= jpeg_quality <= 100:
            raise ValueError("Notebook frame-policy jpeg_quality must be 1 through 100")
        object.__setattr__(self, "jpeg_quality", jpeg_quality)

_control_renderers: dict[str, NotebookControlRenderer] = {}
_frame_policies: dict[str, NotebookFramePolicy] = {}
_DEFAULT_FRAME_POLICY = NotebookFramePolicy()


def _register(
    registry: dict[str, Any],
    kind: str,
    renderer: Any,
    *,
    override: bool,
    label: str,
) -> None:
    key = str(kind).strip()
    if not key:
        raise ValueError(f"Notebook {label} kind must be a non-empty string")
    if not callable(renderer):
        raise TypeError(f"Notebook {label} must be callable")
    current = registry.get(key)
    if current is renderer:
        return
    if current is not None and not override:
        raise ValueError(
            f"Notebook {label} kind {key!r} is already registered; "
            "pass override=True only for an intentional replacement"
        )
    registry[key] = renderer


def register_control_renderer(
    kind: str,
    renderer: NotebookControlRenderer,
    *,
    override: bool = False,
) -> None:
    """Register one ipywidgets control presentation kind."""
    _register(
        _control_renderers,
        kind,
        renderer,
        override=override,
        label="control renderer",
    )


def control_renderer(kind: str) -> NotebookControlRenderer:
    try:
        return _control_renderers[kind]
    except KeyError:
        registered = ", ".join(repr(item) for item in sorted(_control_renderers))
        suffix = f" Registered renderers are {registered}." if registered else ""
        raise ValueError(
            f"No notebook control renderer is registered for {kind!r}.{suffix}"
        ) from None



def register_frame_policy(
    kind: str,
    policy: NotebookFramePolicy | None = None,
    *,
    target_hz: float = 8.0,
    priority: int = 0,
    max_inflight: int = 1,
    raster_scale: float = 1.0,
    jpeg_quality: int = 75,
    override: bool = False,
) -> None:
    """Register notebook raster service policy for one neutral view kind."""
    key = str(kind).strip()
    if not key:
        raise ValueError("Notebook frame-policy kind must be a non-empty string")
    resolved = policy or NotebookFramePolicy(
        target_hz,
        priority,
        max_inflight,
        raster_scale,
        jpeg_quality,
    )
    if not isinstance(resolved, NotebookFramePolicy):
        raise TypeError("Notebook frame policy must be NotebookFramePolicy")
    current = _frame_policies.get(key)
    if current == resolved:
        return
    if current is not None and not override:
        raise ValueError(
            f"Notebook frame policy {key!r} is already registered; "
            "pass override=True only for an intentional replacement"
        )
    _frame_policies[key] = resolved


def frame_policy(kind: str) -> NotebookFramePolicy:
    """Resolve one view kind, falling back to the bounded generic policy."""
    return _frame_policies.get(str(kind).strip(), _DEFAULT_FRAME_POLICY)


def panel_frame_policy(app_spec: Any, panel: Any) -> NotebookFramePolicy:
    """Derive a panel policy only from its registered neutral view kinds."""
    candidates: list[NotebookFramePolicy] = []
    for view_id in panel.view_ids:
        view = app_spec.view(view_id)
        if view is None:
            continue
        policy = frame_policy(view.kind)
        authored_cap = getattr(view, "max_refresh_hz", None)
        if authored_cap is not None and float(authored_cap) > 0.0:
            policy = NotebookFramePolicy(
                min(policy.target_hz, float(authored_cap)),
                policy.priority,
                policy.max_inflight,
                policy.raster_scale,
                policy.jpeg_quality,
            )
        candidates.append(policy)
    if not candidates:
        return _DEFAULT_FRAME_POLICY
    return max(candidates, key=lambda item: (item.priority, item.target_hz))


__all__ = [
    "NotebookControlPresentation",
    "NotebookControlRenderContext",
    "NotebookControlRenderer",
    "NotebookFramePolicy",
    "control_renderer",
    "frame_policy",
    "panel_frame_policy",
    "register_control_renderer",
    "register_frame_policy",
]
