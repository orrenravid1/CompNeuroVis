"""Paint-acknowledged raster canvas for universal notebook frontends.

The widget uses ordinary synced traits through anywidget, so it works in VS
Code notebooks, classic Jupyter, and JupyterLab. A frame credit is returned
only after the browser has decoded and painted the image onto its canvas.
"""

from __future__ import annotations

import struct
from collections.abc import Callable

import anywidget
import traitlets


_ESM = r"""
function render({ model, el }) {
  el.style.display = "block";
  el.style.width = "100%";
  const canvas = document.createElement("canvas");
  canvas.style.cursor = "default";
  canvas.style.display = "block";
  canvas.style.width = "100%";
  canvas.style.height = "auto";
  canvas.style.background = "white";
  el.appendChild(canvas);
  const context = canvas.getContext("2d");
  let drawQueue = Promise.resolve();

  function resize() {
    const width = model.get("width");
    const height = model.get("height");
    const frameWidth = model.get("frame_width") || width;
    const frameHeight = model.get("frame_height") || height;
    canvas.width = frameWidth;
    canvas.height = frameHeight;
    canvas.style.maxWidth = width + "px";
    canvas.style.aspectRatio = width + " / " + height;
  }

  function acknowledge(sequence) {
    model.set("_ack", sequence);
    model.save_changes();
  }

  function drawFrame() {
    const raw = model.get("_frame");
    if (!raw || raw.byteLength < 4) {
      acknowledge(0);
      return;
    }
    const view = raw instanceof DataView
      ? raw
      : new DataView(raw.buffer, raw.byteOffset || 0, raw.byteLength);
    const sequence = view.getUint32(0, false);
    const bytes = new Uint8Array(
      view.buffer,
      view.byteOffset + 4,
      view.byteLength - 4,
    ).slice();
    const format = model.get("format") || "jpeg";
    drawQueue = drawQueue.then(() => new Promise((resolve) => {
      const blob = new Blob([bytes], { type: "image/" + format });
      const url = URL.createObjectURL(blob);
      const image = new Image();
      image.onload = () => {
        context.drawImage(image, 0, 0, canvas.width, canvas.height);
        URL.revokeObjectURL(url);
        acknowledge(sequence);
        resolve();
      };
      image.onerror = () => {
        URL.revokeObjectURL(url);
        acknowledge(sequence);
        resolve();
      };
      image.src = url;
    }));
  }

  resize();
  model.on("change:width", resize);
  model.on("change:height", resize);
  model.on("change:frame_width", resize);
  model.on("change:frame_height", resize);
  model.on("change:_frame", drawFrame);
  drawFrame();

  return () => {
    model.off("change:width", resize);
    model.off("change:height", resize);
    model.off("change:frame_width", resize);
    model.off("change:frame_height", resize);
    model.off("change:_frame", drawFrame);
  };
}
export default { render };
"""


class NotebookRfbWidget(anywidget.AnyWidget):
    """A generic raster panel whose browser paint grants the next frame credit."""

    _esm = _ESM
    width = traitlets.Int(960).tag(sync=True)
    height = traitlets.Int(540).tag(sync=True)
    frame_width = traitlets.Int(960).tag(sync=True)
    frame_height = traitlets.Int(540).tag(sync=True)
    format = traitlets.Unicode("jpeg").tag(sync=True)
    _frame = traitlets.Bytes(b"").tag(sync=True)
    _ack = traitlets.Int(-1).tag(sync=True)

    def __init__(
        self,
        *,
        width: int = 960,
        height: int = 540,
        **kwargs,
    ) -> None:
        super().__init__(
            width=int(width),
            height=int(height),
            frame_width=int(width),
            frame_height=int(height),
            **kwargs,
        )
        self._presented_callbacks: list[Callable[[int], None]] = []
        self._last_sent_sequence = 0
        self._latest_frame_data = b""
        self.observe(self._on_ack_change, names="_ack")

    @property
    def latest_frame_data(self) -> bytes:
        """Latest encoded image bytes, primarily for diagnostics and smoke tests."""
        return self._latest_frame_data

    @property
    def last_sent_sequence(self) -> int:
        return self._last_sent_sequence

    def send_frame(
        self,
        data: bytes,
        *,
        sequence: int,
        image_format: str,
        width: int | None = None,
        height: int | None = None,
    ) -> None:
        sequence = int(sequence)
        if not 0 <= sequence <= 0xFFFFFFFF:
            raise ValueError("Notebook RFB frame sequence must fit uint32")
        self._last_sent_sequence = sequence
        self._latest_frame_data = bytes(data)
        with self.hold_sync():
            self.format = str(image_format)
            if width is not None:
                self.frame_width = int(width)
            if height is not None:
                self.frame_height = int(height)
            self._frame = struct.pack(">I", sequence) + self._latest_frame_data

    def on_presented(self, callback: Callable[[int], None]) -> None:
        if not callable(callback):
            raise TypeError("Notebook RFB presented callback must be callable")
        self._presented_callbacks.append(callback)

    def _on_ack_change(self, change) -> None:
        sequence = int(change.get("new", -1))
        if sequence < 0:
            return
        for callback in tuple(self._presented_callbacks):
            callback(sequence)


__all__ = ["NotebookRfbWidget"]
