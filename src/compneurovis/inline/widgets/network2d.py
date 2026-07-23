"""Network2D widget declaration."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

import numpy as np

from compneurovis.inline.handles import DataHandle, Network2DHandle

if TYPE_CHECKING:
    from compneurovis.inline.widgets.api import WidgetAuthoringContext


@dataclass(frozen=True, slots=True)
class Network2D:
    """A two-dimensional network with optional live node and edge values."""

    name: str
    nodes: Mapping[str, tuple[float, float]]
    edges: Sequence[tuple[str, str] | tuple[str, str, str]]
    node_values: Any = None
    node_read: Callable[[], Any] | None = None
    node_data: DataHandle | None = None
    edge_values: Any = None
    edge_read: Callable[[], Any] | None = None
    edge_data: DataHandle | None = None
    panel_id: str | None = None
    style: Mapping[str, Any] = field(default_factory=dict)

    def attach(self, context: WidgetAuthoringContext) -> Network2DHandle:
        node_names = tuple(str(name) for name in self.nodes)
        edges = tuple(
            (
                str(edge[0]),
                str(edge[1]),
                str(edge[2]) if len(edge) == 3 else f"edge_{index}",
            )
            for index, edge in enumerate(self.edges)
        )
        node_data = _network_data(
            context,
            f"{self.name} nodes",
            values=self.node_values,
            read=self.node_read,
            source=self.node_data,
            labels=node_names,
        )
        edge_data = _network_data(
            context,
            f"{self.name} edges",
            values=self.edge_values,
            read=self.edge_read,
            source=self.edge_data,
            labels=tuple(edge[2] for edge in edges),
        )
        style = dict(self.style)
        title = style.pop("title", self.name)
        max_refresh_hz = style.pop("max_refresh_hz", None)
        panel = context.view(
            "network2d",
            self.name,
            inputs={"nodes": node_data, "edges": edge_data},
            properties={
                "node_positions": tuple(
                    (str(name), float(position[0]), float(position[1]))
                    for name, position in self.nodes.items()
                ),
                "edges": edges,
                **style,
            },
            title=title,
            panel_id=self.panel_id,
            max_refresh_hz=max_refresh_hz,
        )
        return Network2DHandle(panel.id)


def _network_data(
    context: WidgetAuthoringContext,
    name: str,
    *,
    values: Any,
    read: Callable[[], Any] | None,
    source: DataHandle | None,
    labels: Sequence[str],
) -> DataHandle:
    if source is not None:
        return context.data(name, source=source)
    if read is not None:
        return context.data(name, read=read, labels=labels)
    initial = np.zeros(len(labels), dtype=np.float32) if values is None else values
    return context.data(name, values=initial, labels=labels)


__all__ = ["Network2D"]
