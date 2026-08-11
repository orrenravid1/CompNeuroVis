"""Self-closing real-context smoke for the experimental notebook frontend.

Run outside a headless sandbox:

    poetry run python tests/manual_notebook_gui_smoke.py
"""

from __future__ import annotations

import asyncio
import json

import ipywidgets as widgets
import numpy as np
from PyQt6 import QtGui

import compneurovis as cnv
from compneurovis.frontends.vispy.notebook.runtime import (
    build_builder_run_spec,
    start_notebook_app,
)


def _descendants(widget):
    yield widget
    for child in getattr(widget, "children", ()):
        yield from _descendants(child)


def _image_size(data: bytes) -> tuple[int, int]:
    image = QtGui.QImage.fromData(data)
    if image.isNull():
        raise AssertionError("Notebook frame is not a decodable image")
    return image.width(), image.height()


def _foreground_center(data: bytes) -> tuple[float, float]:
    image = QtGui.QImage.fromData(data).convertToFormat(
        QtGui.QImage.Format.Format_RGBA8888
    )
    pointer = image.bits()
    pointer.setsize(image.sizeInBytes())
    rows = np.frombuffer(pointer, dtype=np.uint8).reshape(
        image.height(), image.bytesPerLine()
    )
    rgba = rows[:, : image.width() * 4].reshape(image.height(), image.width(), 4)
    mask = np.min(rgba[:, :, :3], axis=2) < 220
    ys, xs = np.nonzero(mask)
    if not len(xs):
        raise AssertionError("Notebook frame contains no visible foreground")
    return float(np.mean(xs) / image.width()), float(np.mean(ys) / image.height())


def _build_source():
    x = np.linspace(-2.0, 2.0, 32, dtype=np.float32)
    y = np.linspace(-2.0, 2.0, 32, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)
    values = np.exp(-(xx * xx + yy * yy)).astype(np.float32)
    state = {
        "time": 0.0,
        "signal": 0.0,
        "morphology": np.asarray([0.2, 0.8], dtype=np.float32),
    }

    def step(ctx) -> None:
        del ctx
        state["time"] += 8.0
        phase = state["time"] / 100.0
        state["signal"] = float(np.sin(phase))
        state["morphology"] = np.asarray(
            [0.5 + 0.5 * np.sin(phase), 0.5 + 0.5 * np.cos(phase)],
            dtype=np.float32,
        )

    source = cnv.source(step)
    source.surface(
        "Notebook surface smoke",
        values=values,
        x=x,
        y=y,
        color_by="height",
    )
    geometry = cnv.MorphologyGeometry(
        id="notebook_smoke_cable",
        positions=np.asarray(
            [[0.0, 0.0, 0.0], [0.0, 0.0, 2.0]], dtype=np.float32
        ),
        orientations=np.asarray(
            [np.eye(3), np.eye(3)], dtype=np.float32
        ),
        radii=np.asarray([0.5, 0.3], dtype=np.float32),
        lengths=np.asarray([2.0, 2.0], dtype=np.float32),
        entity_ids=("lower", "upper"),
        section_names=("lower", "upper"),
        xlocs=np.asarray([0.25, 0.75], dtype=np.float32),
    )
    source.morphology(
        geometry,
        name="Notebook morphology smoke",
        read=lambda: state["morphology"],
        color_limits=(0.0, 1.0),
    )
    source.line(
        "Notebook line smoke",
        read=lambda: state["signal"],
        x=lambda: state["time"],
    )
    source.slider(
        "gain",
        label="Gain",
        default=1.0,
        min=0.1,
        max=2.0,
        set=lambda ctx, value: None,
    )

    return source


async def _run() -> None:
    handle, root = start_notebook_app(build_builder_run_spec(_build_source))
    try:
        deadline = asyncio.get_running_loop().time() + 30.0
        while True:
            await asyncio.sleep(0.1)
            descendants = tuple(_descendants(root))
            images = tuple(
                widget
                for widget in descendants
                if isinstance(widget, widgets.Image)
            )
            sliders = tuple(
                widget
                for widget in descendants
                if isinstance(widget, widgets.FloatSlider)
            )
            if len(images) == 3 and all(image.value for image in images) and sliders:
                break
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError(
                    "Deferred notebook app did not replace Loading with rendered panels"
                )
        result = {
            "images": len(images),
            "frame_bytes": [len(image.value) for image in images],
            "frame_sizes": [_image_size(image.value) for image in images],
            "formats": [image.format for image in images],
            "foreground_centers": [
                _foreground_center(image.value) for image in images[:2]
            ],
            "controls": len(sliders),
        }
        assert result["images"] == 3
        assert all(result["frame_bytes"])
        assert result["controls"] == 1
        assert result["formats"] == ["jpeg", "jpeg", "jpeg"]
        assert all(
            abs((width / height) - (16.0 / 9.0)) < 0.02
            for width, height in result["frame_sizes"]
        )
        assert all(
            0.35 <= x <= 0.65 and 0.35 <= y <= 0.65
            for x, y in result["foreground_centers"]
        ), result
        initial_frames = tuple(image.value for image in images)
        sliders[0].value = 1.5
        await asyncio.sleep(1.5)
        updated_frames = tuple(image.value for image in images)
        assert updated_frames[0] == initial_frames[0]
        assert updated_frames[1] != initial_frames[1]
        assert updated_frames[2] != initial_frames[2]
        print(json.dumps(result, sort_keys=True), flush=True)
    finally:
        handle.stop()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
