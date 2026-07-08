"""Replay-style animated surface using source-level inline authoring.

Run: python examples/surface_plot/animated_surface_replay.py
"""

from __future__ import annotations

import numpy as np

import compneurovis as cnv


x = np.linspace(-3.0, 3.0, 90, dtype=np.float32)
y = np.linspace(-3.0, 3.0, 90, dtype=np.float32)
X, Y = np.meshgrid(x, y)
frames = tuple(
    (
        np.sin(2.0 * X + phase)
        + np.cos(1.4 * Y - 0.5 * phase)
        + 0.25 * np.sin(X * Y + phase)
    ).astype(np.float32)
    for phase in np.linspace(0.0, 2.0 * np.pi, 180, endpoint=False)
)
state = {"index": 0, "paused": False}


def read_frame() -> np.ndarray:
    return frames[state["index"]]


def step(ctx) -> None:
    if not state["paused"]:
        state["index"] = (state["index"] + 1) % len(frames)


def toggle_pause(ctx) -> None:
    state["paused"] = not state["paused"]


def reset(ctx) -> None:
    state["index"] = 0


src = cnv.source(step)
src.action("pause", label="Pause / resume", fn=toggle_pause)
src.action("reset", label="Restart", fn=reset, resets_fields=True)
surface = src.surface(
    "Replay surface",
    read=read_frame,
    x=x,
    y=y,
    color_map="bwr",
    color_limits=(-2.3, 2.3),
    render_axes=True,
    axis_labels=("x", "y", "height"),
    surface_alpha=0.95,
    camera_distance=70.0,
)

cnv.layout(((surface,), (src.controls_panel,)))

cnv.show(title="Surface replay")
