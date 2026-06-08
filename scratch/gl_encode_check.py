"""Measure readback+encode cost vs resolution and PNG/JPEG. Mirrors notebook _render_morph."""
import io
import time

from vispy import use, scene
use(app="pyqt6", gl="gl+")

import numpy as np
from PIL import Image


def bench(size, n=15):
    c = scene.SceneCanvas(keys="interactive", bgcolor="black", show=False, size=size)
    c.central_widget.add_view()
    c.render()  # warm
    render_ms, png_ms, jpeg_ms, png_kb, jpeg_kb = [], [], [], 0, 0
    for _ in range(n):
        s = time.perf_counter(); rgba = c.render(); render_ms.append((time.perf_counter() - s) * 1000)
        s = time.perf_counter(); b = io.BytesIO(); Image.fromarray(rgba).save(b, format="png"); png_ms.append((time.perf_counter() - s) * 1000); png_kb = len(b.getvalue()) / 1024
        s = time.perf_counter(); b = io.BytesIO(); Image.fromarray(rgba[:, :, :3]).save(b, format="JPEG", quality=70); jpeg_ms.append((time.perf_counter() - s) * 1000); jpeg_kb = len(b.getvalue()) / 1024
    avg = lambda x: sum(x) / len(x)
    print(f"{str(size):>12}  render avg={avg(render_ms):5.1f}  png={avg(png_ms):5.1f}ms/{png_kb:5.0f}kb  jpeg={avg(jpeg_ms):5.1f}ms/{jpeg_kb:5.0f}kb")


for size in [(1200, 480), (800, 320), (600, 240), (400, 160)]:
    bench(size)
