"""Ordinary extension-QWidget panel lifecycle."""

from __future__ import annotations

import time
from typing import Any

from compneurovis.core import ExtensionViewSpec, PanelSpec, app_ref
from compneurovis.frontends.vispy.registries.panel_hosts import PanelHostContext
from compneurovis.frontends.vispy.registries.renderers import create_host
from .contributions import (
    _build_contribution_renderers,
    _refresh_contribution,
    _resolve_properties,
)

DEFAULT_EXTENSION_MAX_REFRESH_HZ = 15.0


class ExtensionPanelLifecycle:
    compact_when_last = False

    def __init__(self, context: PanelHostContext, panel: PanelSpec):
        if len(panel.view_ids) != 1:
            raise ValueError(
                f"Extension panel {panel.id!r} must contain exactly one view id"
            )
        self.context = context
        self.panel = panel
        self.view_id = panel.view_ids[0]
        view = context.app_spec.view(self.view_id)
        if not isinstance(view, ExtensionViewSpec):
            raise TypeError(f"Extension panel {panel.id!r} has no extension view")
        self.host = create_host(
            view,
            panel_id=panel.id,
            view_id=self.view_id,
            title=panel.title or str(view.title or self.view_id),
        )
        self._contribution_renderers = _build_contribution_renderers(
            context, panel, self.host, self.view_id
        )
        self._pending_contributions: set[Any] = set()
        self._pending = False
        self._last_refresh_s: float | None = None

    @property
    def widget(self):
        return self.host

    @property
    def has_pending_refresh(self) -> bool:
        return self._pending or bool(self._pending_contributions)

    def accepts_refresh_target(self, target: Any) -> bool:
        return (
            target.kind == "view" and target.view_id == self.view_id
        ) or (
            target.kind == "visual_contribution"
            and target.panel_id == self.panel.id
            and target.contribution_id in self._contribution_renderers
        )

    def queue_refresh(self, target: Any) -> None:
        if not self.accepts_refresh_target(target):
            return
        if target.kind == "visual_contribution":
            self._pending_contributions.add(target.contribution_id)
        else:
            self._pending = True

    def _interval_s(self, view: ExtensionViewSpec) -> float | None:
        hz = (
            view.max_refresh_hz
            if view.max_refresh_hz is not None
            else DEFAULT_EXTENSION_MAX_REFRESH_HZ
        )
        return None if float(hz) <= 0 else 1.0 / float(hz)

    def flush_refreshes(
        self,
        *,
        force: bool = False,
        now: float | None = None,
        refresh_deadline_s: float | None = None,
    ) -> int:
        if not self.has_pending_refresh:
            return 0
        if refresh_deadline_s is not None and time.monotonic() >= refresh_deadline_s:
            return 0
        current_time = time.monotonic() if now is None else now
        view = self.context.app_spec.view(self.view_id)
        if not isinstance(view, ExtensionViewSpec):
            self._pending = False
            return 0
        interval = self._interval_s(view)
        if (
            not force
            and interval is not None
            and self._last_refresh_s is not None
            and current_time - self._last_refresh_s < interval
        ):
            return 0
        view_ref = app_ref(self.view_id)
        values = self.context.values_for_fragment(view_ref.fragment_id)
        inputs = {
            role: self.context.resolve_input(field_id, view_ref.fragment_id, values)
            for role, field_id in view.inputs.items()
        }
        properties = _resolve_properties(view.properties, values, view_ref.fragment_id)
        if self._pending:
            self.host.refresh(view, inputs, properties, values)
        for contribution_ref in sorted(
            self._pending_contributions, key=str
        ):
            _refresh_contribution(
                self.context,
                contribution_ref,
                self._contribution_renderers[contribution_ref],
            )
        self._last_refresh_s = current_time
        self._pending = False
        self._pending_contributions.clear()
        return 1

    def update_visibility(self) -> None:
        self.host.setVisible(True)

    def dispose(self) -> None:
        self._pending = False
        self._pending_contributions.clear()
        for renderer in self._contribution_renderers.values():
            renderer.clear()


__all__ = ["ExtensionPanelLifecycle"]
