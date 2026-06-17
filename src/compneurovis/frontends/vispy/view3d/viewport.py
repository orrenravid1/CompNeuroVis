from __future__ import annotations

import time
from typing import Protocol

from PyQt6 import QtGui, QtWidgets
from vispy import scene
from vispy.scene.cameras import TurntableCamera

from compneurovis.core._perf import perf_log
from compneurovis.core.app_spec import PanelSpec


class Viewport3DVisual(Protocol):
    def clear(self) -> None:
        ...

    def pick_entity(self, xf: int, yf: int, canvas: scene.SceneCanvas) -> str | None:
        ...


class InstrumentedSceneCanvas(scene.SceneCanvas):
    def __init__(self, *args, perf_panel_id: str | None = None, **kwargs):
        self._perf_panel_id = perf_panel_id
        self._perf_draw_count = 0
        super().__init__(*args, **kwargs)

    def on_draw(self, event) -> None:
        started = time.monotonic()
        super().on_draw(event)
        self._perf_draw_count += 1
        if self._perf_draw_count == 1:
            self._log_gl_info()
        perf_log(
            "view_3d",
            "canvas_draw",
            panel_id=self._perf_panel_id,
            draw_count=self._perf_draw_count,
            width_px=int(self.size[0]),
            height_px=int(self.size[1]),
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )

    def _log_gl_info(self) -> None:
        # One-shot: is this real GPU GL or a software rasterizer (llvmpipe)? A slow
        # draw on a tiny canvas points at software GL or vsync swap-blocking.
        try:
            from vispy.gloo import gl
            info = {
                "renderer": str(gl.glGetParameter(gl.GL_RENDERER)),
                "vendor": str(gl.glGetParameter(gl.GL_VENDOR)),
                "version": str(gl.glGetParameter(gl.GL_VERSION)),
            }
            native_format = getattr(self.native, "format", lambda: None)()
            if native_format is not None:
                info["qt_swap_interval"] = int(native_format.swapInterval())
        except Exception as exc:  # pragma: no cover - diagnostic only
            info = {"error": repr(exc)}
        perf_log("view_3d", "gl_info", panel_id=self._perf_panel_id, **info)


class Viewport3DPanel(QtWidgets.QWidget):
    DRAG_THRESHOLD = 5

    def __init__(
        self,
        *,
        host_spec: PanelSpec | None = None,
        on_entity_selected=None,
        parent=None,
    ):
        super().__init__(parent)
        self._panel_id = host_spec.id if host_spec is not None else None
        self.canvas = InstrumentedSceneCanvas(
            keys="interactive",
            bgcolor="white",
            show=False,
            # vsync off: with vsync on (default), each draw blocks on the display
            # vblank (~tens of ms on Windows/DWM even for a trivial scene), which
            # stalls the Qt UI thread and makes interaction lag. We refresh at a
            # capped rate, so tearing is a non-issue for this data view.
            vsync=False,
            perf_panel_id=self._panel_id,
        )
        self._configure_native_swap_interval()
        self.view = self.canvas.central_widget.add_view()
        distance = 200.0 if host_spec is None else host_spec.camera_distance
        elevation = 30.0 if host_spec is None else host_spec.camera_elevation
        azimuth = 30.0 if host_spec is None else host_spec.camera_azimuth
        self.view.camera = TurntableCamera(
            fov=60,
            distance=distance,
            elevation=elevation,
            azimuth=azimuth,
            translate_speed=100,
            up="+z",
        )
        self.on_entity_selected = on_entity_selected
        self._mouse_start = None
        self._visuals: dict[str, Viewport3DVisual] = {}
        self._active_visual_key: str | None = None

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas.native)

        self.canvas.events.mouse_press.connect(self._on_mouse_press)
        self.canvas.events.mouse_release.connect(self._on_mouse_release)

    def _configure_native_swap_interval(self) -> None:
        native = self.canvas.native
        get_format = getattr(native, "format", None)
        set_format = getattr(native, "setFormat", None)
        if not callable(get_format) or not callable(set_format):
            perf_log(
                "view_3d",
                "canvas_swap_interval_config",
                panel_id=self._panel_id,
                supported=False,
                native_type=type(native).__name__,
            )
            return
        before = get_format()
        fmt = QtGui.QSurfaceFormat(before)
        fmt.setSwapInterval(0)
        set_format(fmt)
        after = get_format()
        perf_log(
            "view_3d",
            "canvas_swap_interval_config",
            panel_id=self._panel_id,
            supported=True,
            native_type=type(native).__name__,
            swap_interval_before=int(before.swapInterval()),
            swap_interval_after=int(after.swapInterval()),
        )

    @property
    def active_visual_key(self) -> str | None:
        return self._active_visual_key

    def mount_visual(self, key: str, visual: Viewport3DVisual) -> None:
        if key in self._visuals:
            raise ValueError(f"3D visual '{key}' is already mounted")
        self._visuals[key] = visual

    def visual(self, key: str) -> Viewport3DVisual:
        try:
            return self._visuals[key]
        except KeyError as exc:
            raise ValueError(f"Unknown 3D visual '{key}'") from exc

    def activate_visual(self, key: str) -> Viewport3DVisual:
        visual = self.visual(key)
        if self._active_visual_key != key:
            self._clear_active_visual()
            self._active_visual_key = key
        self.canvas.native.setVisible(True)
        return visual

    def clear(self) -> None:
        for visual in self._visuals.values():
            visual.clear()
        self._active_visual_key = None
        self.canvas.native.setVisible(False)

    def commit(self) -> None:
        started = time.monotonic()
        self.canvas.update()
        perf_log(
            "view_3d",
            "commit",
            panel_id=self._panel_id,
            active_visual_key=self._active_visual_key,
            width_px=self.width(),
            height_px=self.height(),
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )

    def _clear_active_visual(self) -> None:
        if self._active_visual_key is None:
            return
        self._visuals[self._active_visual_key].clear()

    def _active_visual(self) -> Viewport3DVisual | None:
        if self._active_visual_key is None:
            return None
        return self._visuals[self._active_visual_key]

    def _on_mouse_press(self, ev):
        self._mouse_start = ev.pos
        perf_log(
            "view_3d",
            "mouse_press",
            panel_id=self._panel_id,
            pos=[float(ev.pos[0]), float(ev.pos[1])],
        )

    def _on_mouse_release(self, ev):
        if self._mouse_start is None:
            return
        dx = ev.pos[0] - self._mouse_start[0]
        dy = ev.pos[1] - self._mouse_start[1]
        self._mouse_start = None
        if dx * dx + dy * dy > self.DRAG_THRESHOLD**2:
            return

        visual = self._active_visual()
        entity_id = None
        if visual is not None and self.on_entity_selected is not None:
            x, y = ev.pos
            _, h = self.canvas.size
            ps = self.canvas.pixel_scale
            xf, yf = int(x * ps), int((h - y - 1) * ps)
            entity_id = visual.pick_entity(xf, yf, self.canvas)

        perf_log(
            "view_3d",
            "mouse_release",
            panel_id=self._panel_id,
            pos=[float(ev.pos[0]), float(ev.pos[1])],
            drag_dx=float(dx),
            drag_dy=float(dy),
            picked_entity_id=entity_id,
        )
        if entity_id:
            self.on_entity_selected(entity_id)
