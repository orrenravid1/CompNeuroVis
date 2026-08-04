"""VisPy renderer adapter for the source-level Network2D widget."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from compneurovis.core import ExtensionViewSpec, StateGraphViewSpec
from compneurovis.frontends.vispy.panels.state_graph import GraphHostPanel


class Network2DHostPanel(GraphHostPanel):
    """Extension host: adapts an ``ExtensionViewSpec`` onto the shared graph visual.

    A sibling of :class:`StateGraphHostPanel` -- both feed the same graph
    renderer, neither is a specialization of the other.
    """

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
        self._render(graph_view, inputs.get("nodes"), inputs.get("edges"), values)


__all__ = ["Network2DHostPanel"]
