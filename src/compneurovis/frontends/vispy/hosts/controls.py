"""Controls panel lifecycle."""

from __future__ import annotations

from typing import Any

from compneurovis.core import PanelSpec
from compneurovis.frontends.vispy.controls import ControlsHostPanel, ControlsPanel
from compneurovis.frontends.vispy.refresh_planning import RefreshTarget
from compneurovis.frontends.vispy.registries.panel_hosts import PanelHostContext

class ControlsPanelLifecycle:
    compact_when_last = True

    def __init__(self, context: PanelHostContext, panel: PanelSpec):
        self.context = context
        self.panel = panel
        self.controls_panel = ControlsPanel(
            context.control_changed, context.action_invoked
        )
        self.host = ControlsHostPanel(
            self.controls_panel,
            panel_id=panel.id,
            title=panel.title or "Controls",
        )
        self._pending = False

    @property
    def widget(self):
        return self.host

    @property
    def viewports(self):
        return {}

    @property
    def controls_surface(self):
        return self.controls_panel

    @property
    def has_pending_refresh(self) -> bool:
        return self._pending

    def accepts_refresh_target(self, target: Any) -> bool:
        return target == RefreshTarget.CONTROLS

    def queue_refresh(self, target: Any) -> None:
        if self.accepts_refresh_target(target):
            self._pending = True

    def flush_refreshes(self, **_: Any) -> int:
        if not self._pending:
            return 0
        controls, actions = self.context.controls_and_actions(self.panel.id)
        self.host.set_section_title(
            has_controls=bool(controls), has_actions=bool(actions)
        )
        self.controls_panel.set_controls(
            controls, actions, self.context.value_snapshot()
        )
        self._pending = False
        return 1

    def update_visibility(self) -> None:
        controls, actions = self.context.controls_and_actions(self.panel.id)
        self.host.setVisible(bool(controls or actions))

    def dispose(self) -> None:
        self._pending = False


__all__ = ["ControlsPanelLifecycle"]
