"""VisPy renderer adapter for the source-level Network2D widget."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from compneurovis.core import ExtensionViewSpec, StateGraphViewSpec
from compneurovis.frontends.vispy.panels.state_graph import StateGraphHostPanel


class Network2DHostPanel(StateGraphHostPanel):
    """Render a generic extension frame through the existing graph visual."""

    def refresh(
        self,
        view: ExtensionViewSpec,
        inputs: Mapping[str, Any],
        properties: Mapping[str, Any],
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
        super().refresh(
            graph_view,
            inputs.get("nodes"),
            inputs.get("edges"),
            {},
        )


__all__ = ["Network2DHostPanel"]
