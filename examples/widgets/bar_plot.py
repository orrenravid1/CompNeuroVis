"""Bar plot widget: one bar per category, from literal values.

``bar(values=..., series=...)`` lets the source own the field outright, so a bar
chart needs no simulator. Swap ``values`` for ``read=lambda: ...`` to resample it
every tick, or ``source=`` to plot a field a backend already declares.

Run: python examples/widgets/bar_plot.py
"""

from __future__ import annotations

import compneurovis as cnv


# Mean firing rate per cortical cell type (Hz).
CELL_TYPES = ("Pyramidal", "PV", "SST", "VIP", "Chandelier")
FIRING_RATE_HZ = (4.2, 28.6, 11.3, 7.8, 15.1)

CELL_TYPE_COLORS = {
    "Pyramidal": "#4C72B0",
    "PV": "#CC3311",
    "SST": "#00CC66",
    "VIP": "#E69F00",
    "Chandelier": "#9467BD",
}

rates = cnv.source().bar(
    "Mean firing rate by cell type",
    values=FIRING_RATE_HZ,
    series=CELL_TYPES,
    unit="Hz",
    x_label="Cell type",
    y_label="Firing rate",
    y_min=0.0,
    y_max=32.0,
    series_colors=CELL_TYPE_COLORS,
    background_color="white",
)

cnv.layout(((rates,),))

cnv.show(title="Bar plot - mean firing rate by cell type")
