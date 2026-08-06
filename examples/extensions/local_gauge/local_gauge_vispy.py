"""Vispy-only half of the app-local gauge widget."""

from __future__ import annotations

from PyQt6 import QtWidgets

from compneurovis.frontends.vispy import register_renderer


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


def register() -> None:
    register_renderer("local_gauge", LocalGaugeHost)


__all__ = ["LocalGaugeHost", "register"]
