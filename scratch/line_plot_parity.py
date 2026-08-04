"""Parity test: reproduce the *privileged* built-in line plot as a third-party
extension widget, and show them side by side.

The built-in line plot renders through a hardcoded frontend branch
(``PANEL_KIND_LINE_PLOT`` -> ``LinePlotHostPanel``). This script reproduces it
using ONLY the public extension path:

  * a renderer registered under a brand-new kind ("line_plot_clone"), living in
    an imported module (``line_plot_clone_renderer``) exactly as built-ins
    register at import -- NOT in this script's top level, which the actor
    architecture re-runs;
  * a widget authored purely through ``context`` (``context.series`` +
    ``context.view``), with no library-private hook.

If the two panels look identical while playing, "one path" holds: a third-party
widget matches a privileged built-in.

Run: python scratch/line_plot_parity.py
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import compneurovis as cnv
from compneurovis.inline.refs import PanelRef
from compneurovis.inline.widgets.api import Widget

# Importing the renderer module registers "line_plot_clone" at import time.
import line_plot_clone_renderer  # noqa: F401


# --- the "third-party" widget: authored ONLY through context -------------------
@dataclass(frozen=True, slots=True)
class LinePlotClone(Widget[PanelRef]):
    name: str
    read: Any
    x: Any = None
    style: Mapping[str, Any] = field(default_factory=dict)

    def declare(self, context) -> PanelRef:
        data = context.series(self.name, read=self.read, x=self.x)
        return context.view(
            "line_plot_clone",
            self.name,
            inputs={"data": data},
            properties={"x_dim": "time", "series_dim": "series", **self.style},
        )


# --- app: built-in line plot vs the third-party clone, identical data ----------
state = {"t": 0.0}


def step(ctx):
    state["t"] += 1.0


def signal() -> float:
    return math.sin(state["t"] * 0.1) * 40.0


STYLE = {"y_min": -50.0, "y_max": 50.0, "color": "#4fc3f7", "y_label": "amplitude"}

src = cnv.source(step)
builtin = src.line("Built-in line", read=signal, x=lambda: state["t"], **STYLE)
clone = src.add(LinePlotClone("Third-party clone", read=signal, x=lambda: state["t"], style=STYLE))
cnv.layout(((builtin, clone),))
cnv.show(title="Parity: built-in line plot vs third-party clone")
