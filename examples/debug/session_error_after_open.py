"""Open a source app, then raise from the source step to exercise error reporting.

Run: python examples/debug/session_error_after_open.py
"""

from __future__ import annotations

import compneurovis as cnv


state = {"t": 0.0, "value": 0.0}


def step(ctx) -> None:
    state["t"] += 1.0
    state["value"] += 0.1
    if state["t"] > 120.0:
        raise RuntimeError("Intentional debug failure after the app has opened")


src = cnv.source(step)
src.line("Debug signal", x=lambda: state["t"], read=lambda: state["value"], rolling_window=150.0)

cnv.show(title="Debug error after open")
