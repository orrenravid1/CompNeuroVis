"""Vispy-only half of the app-local gauge widget."""

from __future__ import annotations

from PyQt6 import QtWidgets

from compneurovis import app_ref
from compneurovis.frontends.vispy import register_panel_host


class LocalGaugeHost(QtWidgets.QGroupBox):
    def __init__(self, *, panel_id, view_id, title):
        del panel_id, view_id
        super().__init__(title)
        self._bar = QtWidgets.QProgressBar()
        self._bar.setRange(0, 100)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self._bar)

    def refresh(self, view, inputs, properties, values):
        del view, properties, values
        field = inputs["data"]
        value = float(field.values.reshape(-1)[-1])
        self._bar.setValue(round(100.0 * max(0.0, min(1.0, value))))


class LocalGaugePanelLifecycle:
    """A complete third-party panel lifecycle with no frontend special case."""

    compact_when_last = False

    def __init__(self, context, panel):
        if len(panel.view_ids) != 1:
            raise ValueError("A local gauge panel owns exactly one view")
        self.context = context
        self.panel = panel
        self.view_id = panel.view_ids[0]
        view = context.app_spec.view(self.view_id)
        self.host = LocalGaugeHost(
            panel_id=panel.id,
            view_id=self.view_id,
            title=panel.title or str(view.title or self.view_id),
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
        return None

    @property
    def has_pending_refresh(self):
        return self._pending

    def accepts_refresh_target(self, target):
        return target.kind == "extension" and target.view_id == self.view_id

    def queue_refresh(self, target):
        if self.accepts_refresh_target(target):
            self._pending = True

    def flush_refreshes(self, **kwargs):
        del kwargs
        if not self._pending:
            return 0
        view = self.context.app_spec.view(self.view_id)
        view_ref = app_ref(self.view_id)
        values = self.context.values_for_fragment(view_ref.fragment_id)
        inputs = {
            role: self.context.resolve_input(field_id, view_ref.fragment_id, values)
            for role, field_id in view.inputs.items()
        }
        self.host.refresh(view, inputs, {}, values)
        self._pending = False
        return 1

    def update_visibility(self):
        self.host.setVisible(True)

    def dispose(self):
        self._pending = False


def register() -> None:
    register_panel_host("local_gauge_panel", LocalGaugePanelLifecycle)


__all__ = ["LocalGaugeHost", "LocalGaugePanelLifecycle", "register"]
