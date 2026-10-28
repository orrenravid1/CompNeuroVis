"""Network2D widget: a fixed kinetic scheme colored by occupancy and flux.

Nodes are colored by state occupancy, edges by net flux. Both follow the same
data vocabulary as every other widget: values for a static snapshot, readers
for live data, and data handles for optimized simulator-owned data.

The label offsets are wired to sliders so the node text can be nudged onto the
node centre by eye; they are in pixels, +x right and +y up.

Run: python examples/widgets/network2d.py
"""

from __future__ import annotations

import compneurovis as cnv


# A canonical ion-channel gating scheme: three closed states, one open, one
# inactivated. Positions are (state, x, y) in normalized [0, 1] canvas space.
NODES = {
    "C1": (0.10, 0.68),
    "C2": (0.33, 0.68),
    "C3": (0.56, 0.68),
    "O": (0.80, 0.68),
    "I": (0.80, 0.24),
}

# (source_state, target_state, edge)
EDGES = (
    ("C1", "C2", "C1->C2"),
    ("C2", "C3", "C2->C3"),
    ("C3", "O", "C3->O"),
    ("O", "C3", "O->C3"),
    ("O", "I", "O->I"),
    ("I", "C1", "I->C1"),
)

# Occupancy per state (sums to 1) at the peak of the open probability.
OCCUPANCY = (0.05, 0.12, 0.18, 0.55, 0.10)

# Net flux along each edge; negative means net flow against the arrow.
FLUX = (0.041, 0.063, 0.085, -0.024, 0.032, 0.018)

# Aquamarine: pale mint -> aquamarine -> sea green -> deep teal.
NODE_COLOR_MAP = "ramp:#eafff8:#7fffd4:#1fb2a6:#0b4f4a"
# Diverging about zero flux, so reverse flux reads as rose against the teal.
EDGE_COLOR_MAP = "ramp:#c1436d:#e8f6f3:#0f9b8e"


def slider(source, name, label, default, min_value, max_value, steps):
    return source.slider(name, label=label, default=default, min=min_value, max=max_value, steps=steps)


src = cnv.source()
label_offset_x = slider(src, "label_offset_x", "Label offset x (px)", 0.0, -12.0, 12.0, 96)
label_offset_y = slider(src, "label_offset_y", "Label offset y (px)", 0.0, -12.0, 12.0, 96)
label_size = slider(src, "label_size", "Label size", 10.0, 4.0, 28.0, 96)
node_size = slider(src, "node_size", "Node size", 38.0, 10.0, 90.0, 80)
edge_width = slider(src, "edge_width", "Edge width", 5.0, 1.0, 14.0, 52)
arrow_size = slider(src, "arrow_size", "Arrow size", 12.0, 4.0, 40.0, 72)

scheme = src.network2d(
    "Ion channel gating scheme",
    nodes=NODES,
    edges=EDGES,
    node_values=OCCUPANCY,
    edge_values=FLUX,
    node_color_map=NODE_COLOR_MAP,
    node_color_limits=(0.0, 0.6),
    edge_color_map=EDGE_COLOR_MAP,
    edge_color_limits=(-0.1, 0.1),
    node_size=node_size,
    edge_width=edge_width,
    arrow_size=arrow_size,
    label_size=label_size,
    label_offset_x=label_offset_x,
    label_offset_y=label_offset_y,
    background_color="white",
)

cnv.layout(((scheme,), (src.controls_panel,)))

cnv.show(title="State graph - ion channel gating scheme")
