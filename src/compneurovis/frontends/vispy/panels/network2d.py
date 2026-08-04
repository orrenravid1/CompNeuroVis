"""VisPy renderer adapter for the source-level Network2D widget."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PyQt6 import QtWidgets

from compneurovis.core import ExtensionViewSpec, StateGraphViewSpec
from compneurovis.frontends.vispy.panels.state_graph import StateGraphPanel


class Network2DHostPanel(QtWidgets.QGroupBox):
    """Extension host: render an ``ExtensionViewSpec(kind="network2d")`` on the
    shared node/edge graph visual (:class:`StateGraphPanel`).

    Network2D is the sole consumer of that visual (the native state-graph view
    path was removed), so this host wraps the visual directly and adapts the
    extension view into the render config the visual expects.
    """

    def __init__(self, *, panel_id: str, view_id: str, title: str | None = None, parent=None):
        super().__init__(title or view_id, parent)
        self.panel_id = panel_id
        self.view_id = view_id
        self.state_graph_panel = StateGraphPanel(perf_panel_id=panel_id, perf_view_id=view_id)
        self._last_title = str(title or view_id)
        lo = QtWidgets.QVBoxLayout(self)
        lo.setContentsMargins(4, 8, 4, 4)
        lo.addWidget(self.state_graph_panel)

    def refresh(
        self,
        view: ExtensionViewSpec,
        inputs: Mapping[str, Any],
        properties: Mapping[str, Any],
        values: Mapping[str, Any] | None = None,
    ) -> None:
        style = dict(properties)
        node_positions = tuple(style.pop("node_positions"))
        edges = tuple(style.pop("edges"))
        graph_view = StateGraphViewSpec(
            id=view.id,
            title=view.title,
            node_field_id=view.inputs.get("nodes", ""),
            edge_field_id=view.inputs.get("edges", ""),
            node_positions=node_positions,
            edges=edges,
            max_refresh_hz=view.max_refresh_hz,
            **style,
        )
        title = str(view.title or self.view_id)
        if title != self._last_title:
            self.setTitle(title)
            self._last_title = title
        self.state_graph_panel.refresh(graph_view, inputs.get("nodes"), inputs.get("edges"), values)


__all__ = ["Network2DHostPanel"]
