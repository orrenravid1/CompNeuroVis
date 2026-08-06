"""Open panel-host lifecycle registry for the Vispy frontend.

This module deliberately has no Qt or Vispy imports.  App-local code may defer
a plugin callback from the authoring process without importing the GUI stack;
the callback registers its panel host only when the frontend loads plugins.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from compneurovis.core import AppRef, AppSpec, Field, PanelSpec


@dataclass(frozen=True)
class PanelHostContext:
    """Stable services available to a panel-host factory.

    The context exposes data and interaction capabilities, not the frontend
    window.  A third-party host therefore cannot depend on window internals.
    """

    app_spec: AppSpec
    active_layout: Callable[[], Any]
    value_snapshot: Callable[[], dict[Any, Any]]
    values_for_fragment: Callable[[str], dict[Any, Any]]
    field: Callable[..., Field | None]
    fields: Callable[[], Mapping[Any, Field]]
    resolve_input: Callable[[str, str, dict[Any, Any]], Field | None]
    controls_and_actions: Callable[[str], tuple[list[Any], list[Any]]]
    control_changed: Callable[[Any, Any], None]
    action_invoked: Callable[[Any, dict[str, Any]], None]
    entity_selected: Callable[[str | AppRef, str], None]


@runtime_checkable
class PanelHostLifecycle(Protocol):
    """Complete lifecycle owned by one mounted panel host."""

    @property
    def widget(self) -> Any:
        """The QWidget placed in the resolved layout cell."""

    @property
    def has_pending_refresh(self) -> bool:
        """Whether queued work remains for a later cadence flush."""

    @property
    def compact_when_last(self) -> bool:
        """Whether a final-row host prefers compact vertical allocation."""

    def accepts_refresh_target(self, target: Any) -> bool:
        """Return whether this mounted host owns a neutral refresh target."""

    def queue_refresh(self, target: Any) -> None:
        """Queue a refresh target accepted by this host."""

    def flush_refreshes(
        self,
        *,
        force: bool = False,
        now: float | None = None,
        refresh_deadline_s: float | None = None,
    ) -> int:
        """Apply due work and return the number of refreshed views/panels."""

    def update_visibility(self) -> None:
        """Re-evaluate visibility after app or layout changes."""

    def dispose(self) -> None:
        """Release host-owned resources before the panel is discarded."""


PanelHostFactory = Callable[[PanelHostContext, PanelSpec], PanelHostLifecycle]

_panel_host_factories: dict[str, PanelHostFactory] = {}


def register_panel_host(
    kind: str,
    factory: PanelHostFactory,
    *,
    override: bool = False,
) -> None:
    """Register the complete Vispy lifecycle for one neutral panel kind."""
    normalized = str(kind).strip()
    if not normalized:
        raise ValueError("Panel-host kind must be a non-empty string")
    if not callable(factory):
        raise TypeError("Panel-host factory must be callable")
    current = _panel_host_factories.get(normalized)
    if current is factory:
        return
    if current is not None and not override:
        raise ValueError(
            f"Vispy panel host {normalized!r} is already registered; "
            "pass override=True only for an intentional replacement"
        )
    _panel_host_factories[normalized] = factory


def panel_host_factory(kind: str) -> PanelHostFactory:
    """Resolve a panel-host factory or fail with the live registered set."""
    try:
        return _panel_host_factories[kind]
    except KeyError:
        supported = ", ".join(repr(item) for item in registered_panel_kinds())
        suffix = f" Registered kinds are {supported}." if supported else ""
        raise LookupError(
            f"Vispy has no panel host registered for kind {kind!r}.{suffix} "
            "Register one from a deferred Vispy plugin callback."
        ) from None


def registered_panel_kinds() -> tuple[str, ...]:
    """Return the currently registered panel kinds in deterministic order."""
    return tuple(sorted(_panel_host_factories))


def panel_host_factories() -> Mapping[str, PanelHostFactory]:
    """Return a read-only snapshot useful for diagnostics."""
    return dict(_panel_host_factories)


__all__ = [
    "PanelHostContext",
    "PanelHostFactory",
    "PanelHostLifecycle",
    "panel_host_factories",
    "panel_host_factory",
    "register_panel_host",
    "registered_panel_kinds",
]
