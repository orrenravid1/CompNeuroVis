"""Universal remote-framebuffer widget for notebook morphology rendering.

Replicates the part of ``jupyter_rfb`` that matters — **backpressure** — using
``anywidget`` so it loads in every notebook frontend (VS Code, classic Jupyter,
JupyterLab, Colab), not just JupyterLab.

Everything goes over **synced traits** (the same binary channel that backs
``ipywidgets.Image.value``), not custom ``model.send``/``on_msg`` messages —
the latter are unreliable in some frontends (notably VS Code).

Flow:
    server sets ``_frame`` (bytes) ──► client draws to <canvas>
        ▲                                   │
        └──── client bumps ``_ack`` ◄───────┘  (ack AFTER paint)

The server emits the next frame only once ``_ack`` advances, so frames are
*pulled* at the rate the comm + browser can sustain. Pointer/wheel deltas come
back through the ``_camera`` trait, so input never competes with frame bytes.
"""
from __future__ import annotations

from typing import Callable

import anywidget
import traitlets

# --------------------------------------------------------------------------- #
# Frontend (ESM) — loaded uniformly across notebook frontends by anywidget.    #
# --------------------------------------------------------------------------- #
_ESM = r"""
function render({ model, el }) {
  const w = model.get("width");
  const h = model.get("height");

  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  canvas.style.width = w + "px";
  canvas.style.height = h + "px";
  canvas.style.cursor = "grab";
  canvas.style.touchAction = "none";
  canvas.style.background = "black";
  el.appendChild(canvas);
  const ctx = canvas.getContext("2d");

  function ack() {
    model.set("_ack", model.get("_ack") + 1);
    model.save_changes();
  }

  function drawFrame() {
    const buf = model.get("_frame");
    if (!buf || buf.byteLength === 0) { ack(); return; }
    const bytes = buf instanceof DataView ? buf : new DataView(buf.buffer || buf);
    const blob = new Blob([bytes], { type: "image/jpeg" });
    const url = URL.createObjectURL(blob);
    const im = new Image();
    im.onload = () => {
      ctx.drawImage(im, 0, 0, canvas.width, canvas.height);
      URL.revokeObjectURL(url);
      ack();                       // pull next frame only after this paint
    };
    im.onerror = () => { URL.revokeObjectURL(url); ack(); };
    im.src = url;
  }

  model.on("change:_frame", drawFrame);

  // ---- outgoing camera deltas via trait sync ----------------------------- //
  let seq = 0;
  function sendCamera(ev) {
    ev.seq = ++seq;              // force a trait change even on repeats
    model.set("_camera", ev);
    model.save_changes();
  }

  let dragging = false, lastX = 0, lastY = 0;
  canvas.addEventListener("pointerdown", (e) => {
    dragging = true; lastX = e.offsetX; lastY = e.offsetY;
    try { canvas.setPointerCapture(e.pointerId); } catch (_) {}
    canvas.style.cursor = "grabbing";
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const dx = e.offsetX - lastX, dy = e.offsetY - lastY;
    lastX = e.offsetX; lastY = e.offsetY;
    if (dx !== 0 || dy !== 0) sendCamera({ type: "orbit", dx: dx, dy: dy });
  });
  const endDrag = () => { dragging = false; canvas.style.cursor = "grab"; };
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointercancel", endDrag);
  canvas.addEventListener("pointerleave", endDrag);
  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    sendCamera({ type: "zoom", delta: e.deltaY });
  }, { passive: false });

  // bootstrap: ack once on mount so the server sends the first frame, and draw
  // anything already present.
  drawFrame();
  ack();
}
export default { render };
"""


class MorphRfbWidget(anywidget.AnyWidget):
    """Canvas widget that pulls JPEG frames from the server with backpressure.

    Pure trait-sync transport (no custom messages):

    * ``send_frame(jpeg_bytes)``  — server → client (sets ``_frame``)
    * ``on_ready(cb)``            — client acked the last paint (``_ack`` rose)
    * ``on_camera(cb)``           — client orbit/zoom delta (``_camera`` changed)
    """

    _esm = _ESM
    width = traitlets.Int(800).tag(sync=True)
    height = traitlets.Int(320).tag(sync=True)
    _frame = traitlets.Bytes(b"").tag(sync=True)
    _ack = traitlets.Int(0).tag(sync=True)
    _camera = traitlets.Dict().tag(sync=True)

    def __init__(self, *, width: int = 800, height: int = 320, **kwargs) -> None:
        super().__init__(width=width, height=height, **kwargs)
        self._ready_cbs: list[Callable[[], None]] = []
        self._camera_cbs: list[Callable[[dict], None]] = []
        self.observe(self._on_ack_change, names="_ack")
        self.observe(self._on_camera_change, names="_camera")

    def send_frame(self, data: bytes) -> None:
        self._frame = data

    def on_ready(self, cb: Callable[[], None]) -> None:
        self._ready_cbs.append(cb)

    def on_camera(self, cb: Callable[[dict], None]) -> None:
        self._camera_cbs.append(cb)

    def _on_ack_change(self, _change) -> None:
        for cb in self._ready_cbs:
            cb()

    def _on_camera_change(self, change) -> None:
        event = change.get("new") or {}
        for cb in self._camera_cbs:
            cb(event)


__all__ = ["MorphRfbWidget"]
