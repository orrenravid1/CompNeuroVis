"""Diagnose offscreen vs shown GL context + render cost. Notebook path uses offscreen + render()."""
import time

from vispy import use, scene
use(app="pyqt6", gl="gl+")

import numpy as np
from vispy.gloo import gl


def renderer_string(canvas):
    canvas.set_current()
    parts = {}
    for name, enum in (("vendor", gl.GL_VENDOR), ("renderer", gl.GL_RENDERER), ("version", gl.GL_VERSION)):
        try:
            parts[name] = gl.glGetParameter(enum)
        except Exception as exc:
            parts[name] = f"<err {exc}>"
    return parts


def time_render(canvas, n=10):
    canvas.render()  # warmup
    t = []
    for _ in range(n):
        s = time.perf_counter()
        canvas.render()
        t.append((time.perf_counter() - s) * 1000.0)
    return min(t), sum(t) / len(t), max(t)


print("=== OFFSCREEN (show=False) — notebook path ===")
off = scene.SceneCanvas(keys="interactive", bgcolor="black", show=False, size=(1200, 480))
off.central_widget.add_view()
print("GL:", renderer_string(off))
lo, avg, hi = time_render(off)
print(f"canvas.render() ms  min={lo:.1f} avg={avg:.1f} max={hi:.1f}")

print()
print("=== SHOWN (show=True) — desktop-like context ===")
shown = scene.SceneCanvas(keys="interactive", bgcolor="black", show=True, size=(1200, 480))
shown.central_widget.add_view()
shown.app.process_events()
print("GL:", renderer_string(shown))
lo, avg, hi = time_render(shown)
print(f"canvas.render() ms  min={lo:.1f} avg={avg:.1f} max={hi:.1f}")
