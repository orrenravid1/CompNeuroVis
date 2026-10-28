from __future__ import annotations

from PyQt6 import QtWidgets
from PyQt6.QtCore import Qt

from .panel import ControlsPanel


class ControlsHostPanel(QtWidgets.QGroupBox):
    def __init__(
        self,
        controls_panel: ControlsPanel,
        *,
        panel_id: str,
        title: str = "Controls",
        parent=None,
    ):
        super().__init__(title, parent)
        self.panel_id = panel_id
        self.controls_panel = controls_panel
        self.scroll_area = QtWidgets.QScrollArea(self)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll_area.setWidget(self.controls_panel)
        self.setMinimumHeight(0)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Expanding,
            QtWidgets.QSizePolicy.Policy.Ignored,
        )
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 4)
        layout.addWidget(self.scroll_area)

    def set_section_title(self, *, has_controls: bool, has_actions: bool) -> None:
        if has_controls and has_actions:
            self.setTitle("Controls & Actions")
        elif has_actions:
            self.setTitle("Actions")
        else:
            self.setTitle("Controls")
