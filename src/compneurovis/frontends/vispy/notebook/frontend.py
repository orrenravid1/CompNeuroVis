"""Generic ipywidgets projection of registered Vispy panel lifecycles."""

from __future__ import annotations

import html
import sys
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
from PyQt6 import QtCore, QtGui, QtWidgets
from PyQt6.QtCore import Qt

from compneurovis.core import AppSpec
from compneurovis.core.messages import (
    BeginExecution,
    Error,
    FramePresented,
    Message,
    MessagePayload,
    RenderedFrame,
)
from compneurovis.frontends.base import FrontendBase
from compneurovis.frontends.vispy.bindings import resolve_binding
from compneurovis.frontends.vispy.frontend import VispyFrontendWindow
from compneurovis.frontends.vispy.notebook.builtins import (
    register_first_party_notebook_presentations,
)
from compneurovis.frontends.vispy.notebook.registries import (
    NotebookActionRenderContext,
    NotebookControlPresentation,
    NotebookControlRenderContext,
    action_renderer,
    control_renderer,
    panel_frame_policy,
)
from compneurovis.frontends.vispy.notebook.rfb_widget import NotebookRfbWidget
from compneurovis.frontends.vispy.registries.controls import (
    ResolvedAction,
    ResolvedControl,
)
from compneurovis.core.runtime.performance import perf_log, perf_logging_enabled


DEFAULT_RENDER_HZ = 30.0
DEFAULT_PANEL_WIDTH = 960
DEFAULT_PANEL_HEIGHT = 540


@dataclass(slots=True)
class _ControlBinding:
    resolved: ResolvedControl
    presentation: NotebookControlPresentation
    syncing: bool = False


def _configure_notebook_vispy_backend() -> None:
    """Select desktop OpenGL before the generic panel graph creates canvases.

    Vispy's default ``gl2`` wrapper omits instanced draw entry points used by
    first- and third-party visuals. Notebook raster projection still renders on
    the local GPU, so it needs the same ``gl+`` backend as desktop.
    """
    from vispy import use

    use(app="pyqt6", gl="gl+")


def _qimage_bytes(
    image: QtGui.QImage, *, image_format: str, quality: int = -1
) -> bytes:
    buffer = QtCore.QBuffer()
    buffer.open(QtCore.QIODevice.OpenModeFlag.WriteOnly)
    try:
        if not image.save(buffer, image_format, quality):
            raise RuntimeError(
                f"Qt could not encode a notebook panel as {image_format}"
            )
        return bytes(buffer.data())
    finally:
        buffer.close()


def _array_jpeg(values: Any, *, quality: int = 75) -> bytes:
    rgba = np.asarray(values)
    if rgba.ndim != 3 or rgba.shape[2] not in (3, 4):
        raise ValueError("Notebook panel images must have RGB or RGBA shape")
    if rgba.dtype != np.uint8:
        rgba = np.clip(rgba, 0.0, 1.0)
        rgba = np.round(rgba * 255.0).astype(np.uint8)
    rgba = np.ascontiguousarray(rgba)
    height, width, channels = rgba.shape
    image_format = (
        QtGui.QImage.Format.Format_RGBA8888
        if channels == 4
        else QtGui.QImage.Format.Format_RGB888
    )
    image = QtGui.QImage(
        rgba.data,
        width,
        height,
        int(rgba.strides[0]),
        image_format,
    ).copy()
    return _qimage_bytes(image, image_format="JPEG", quality=quality)


def _render_widget_image(
    widget: QtWidgets.QWidget,
    *,
    logical_size: tuple[int, int],
    raster_scale: float,
) -> QtGui.QImage:
    """Render a QWidget at higher physical resolution without changing layout."""
    logical_width, logical_height = logical_size
    pixel_width = max(1, int(round(logical_width * raster_scale)))
    pixel_height = max(1, int(round(logical_height * raster_scale)))
    image = QtGui.QImage(
        pixel_width,
        pixel_height,
        QtGui.QImage.Format.Format_RGB32,
    )
    image.fill(QtGui.QColor("white"))
    painter = QtGui.QPainter(image)
    try:
        painter.setRenderHints(
            QtGui.QPainter.RenderHint.Antialiasing
            | QtGui.QPainter.RenderHint.TextAntialiasing
            | QtGui.QPainter.RenderHint.SmoothPixmapTransform
        )
        painter.scale(
            pixel_width / logical_width,
            pixel_height / logical_height,
        )
        widget.render(painter)
    finally:
        painter.end()
    return image


class NotebookFrontend(FrontendBase):
    """Notebook shell over the canonical application projection.

    With external frames, the kernel owns only structure, values, controls, and
    outbound actions. The renderer process alone mounts VisPy panels and OpenGL
    resources. Explicit in-kernel rendering still uses the ordinary registered
    VisPy panel graph.
    """

    def __init__(
        self,
        *,
        render_hz: float = DEFAULT_RENDER_HZ,
        panel_size: tuple[int, int] = (
            DEFAULT_PANEL_WIDTH,
            DEFAULT_PANEL_HEIGHT,
        ),
        external_frames: bool = False,
        panel_capture_budget: int = 1,
        automatic_capture: bool = True,
        begin_on_first_paint: bool = False,
    ) -> None:
        super().__init__()
        import ipywidgets as widgets

        register_first_party_notebook_presentations()
        self._widgets = widgets
        self._render_interval = 1.0 / max(float(render_hz), 1.0)
        self._panel_size = (int(panel_size[0]), int(panel_size[1]))
        self._external_frames = bool(external_frames)
        self._panel_capture_budget = max(1, int(panel_capture_budget))
        self._automatic_capture = bool(automatic_capture)
        self._begin_on_first_paint = bool(begin_on_first_paint)
        self._execution_begun = not self._begin_on_first_paint
        if not self._external_frames:
            _configure_notebook_vispy_backend()
        self._last_render = 0.0
        self._render_due = False
        self._structure_signature: Any = None
        self._panel_images: dict[str, Any] = {}
        self._last_panel_frame: dict[str, tuple[str, bytes]] = {}
        self._last_panel_dimensions: dict[str, tuple[int, int]] = {}
        self._captured_panel_revisions: dict[str, int] = {}
        self._capture_surface_lifecycles: dict[str, Any] = {}
        self._pending_external_frames: dict[str, RenderedFrame] = {}
        self._presented_external_frames: dict[
            str, tuple[str, bytes, int | None, int | None]
        ] = {}
        self._capture_cursor = 0
        self._control_bindings: dict[Any, _ControlBinding] = {}
        self._perf_trace_sequence = 0
        self._perf_frame_window_started = time.monotonic()
        self._perf_frame_count = 0
        self._perf_frame_bytes = 0
        self._perf_frame_apply_ms = 0.0
        self._perf_frame_apply_ms_max = 0.0
        self.stop_requested = False

        self._loading = widgets.HTML(value="<i>Loading CompNeuroVis app...</i>")
        self._stop_button = widgets.Button(
            description="Stop",
            button_style="danger",
            layout=widgets.Layout(width="80px"),
        )
        self._stop_button.on_click(
            lambda _button: setattr(self, "stop_requested", True)
        )
        self.widget = widgets.VBox([self._loading, self._stop_button])

        self._qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.window = VispyFrontendWindow(
            title="CompNeuroVis notebook",
            mount_panels=not self._external_frames,
        )
        self.window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.window.resize(1280, 720)

    @property
    def app_spec(self) -> AppSpec | None:
        return self.window.app_spec

    def initialize(self, app_spec: AppSpec | None) -> None:
        started = time.monotonic()
        self.window.initialize(app_spec)
        self.window.show()
        self._qapp.processEvents()
        if self.window.app_spec is not None:
            self._sync_structure(force=True)
            self._render_due = not self._external_frames
        self._drain_window_messages()
        perf_log(
            "notebook_frontend",
            "initialize",
            external_frames=self._external_frames,
            panel_count=len(self._panel_images),
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )

    def handle(self, message: Message[MessagePayload]) -> None:
        self.handle_messages([message])

    def handle_messages(self, messages: list[Message[MessagePayload]]) -> None:
        """Apply one transport poll as a compacted frontend update batch."""
        if not messages:
            return
        started = time.monotonic()
        local_messages = []
        latest_frames: dict[str, tuple[RenderedFrame, Any]] = {}
        frame_count = 0
        for message in messages:
            if isinstance(message.payload, RenderedFrame):
                frame_count += 1
                self._pending_external_frames[message.payload.frame_id] = (
                    message.payload
                )
                latest_frames[message.payload.frame_id] = (
                    message.payload,
                    message.tags,
                )
                continue
            local_messages.append(message)
            if isinstance(message.payload, Error):
                sys.stderr.write(
                    "[CompNeuroVis source error]\n"
                    f"{message.payload.message.rstrip()}\n"
                )
                sys.stderr.flush()
        if local_messages:
            compacted = self.window.compact_update_messages(local_messages)
            self.window._handle_update_messages(
                compacted,
                poll_started=time.monotonic(),
                timer_gap_ms=None,
            )
            self._sync_structure()
            self._sync_control_values()
        for frame, tags in latest_frames.values():
            self._apply_external_frame(frame, tags=tags)
        self._drain_window_messages()
        if not self._external_frames:
            self._render_due = (
                self._has_uncaptured_panel_refreshes()
                or self.window.panel_manager.has_pending_refreshes()
            )
        perf_log(
            "notebook_frontend",
            "message_batch",
            message_count=len(messages),
            frame_count=frame_count,
            local_update_count=len(local_messages),
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )

    def tick(self) -> None:
        self._qapp.processEvents()
        if self._external_frames:
            self._drain_window_messages()
            return
        self.window.flush_due_refreshes(now=time.monotonic())
        self._drain_window_messages()
        if not self._automatic_capture:
            return
        self._render_due = (
            self._render_due
            or self._has_uncaptured_panel_refreshes()
        )
        if not self._render_due or self.window.app_spec is None:
            return
        now = time.monotonic()
        if now - self._last_render < self._render_interval:
            return
        self.render_panels()
        self._last_render = now
        self._render_due = (
            self.window.panel_manager.has_pending_refreshes()
            or self._has_uncaptured_panel_refreshes()
        )

    def is_active(self) -> bool:
        return True

    def idle_sleep(self) -> float:
        return min(self._render_interval, 1.0 / 30.0)

    def shutdown(self) -> None:
        self.window.close()
        close = getattr(self.widget, "close", None)
        if callable(close):
            close()

    def render_panels(self) -> None:
        """Capture dirty panels within the app-wide presentation budget."""
        if self._external_frames:
            return
        self._qapp.processEvents()
        panel_ids = tuple(self._panel_images)
        if not panel_ids:
            return
        captured = 0
        for offset in range(len(panel_ids)):
            index = (self._capture_cursor + offset) % len(panel_ids)
            panel_id = panel_ids[index]
            image_widget = self._panel_images[panel_id]
            captured_frame = self.capture_dirty_panel(panel_id)
            if captured_frame is None:
                continue
            captured += 1
            self._capture_cursor = (index + 1) % len(panel_ids)
            image_format, data, _, _ = captured_frame
            image_widget.format = image_format
            image_widget.value = data
            if captured >= self._panel_capture_budget:
                break

    def panel_ids(self) -> tuple[str, ...]:
        return tuple(self._panel_images)

    def dirty_panel_ids(self) -> tuple[str, ...]:
        revisions = self.window.panel_manager.panel_refresh_revisions()
        return tuple(
            panel_id
            for panel_id in self._panel_images
            if panel_id not in self._last_panel_frame
            or self._captured_panel_revisions.get(panel_id)
            != revisions.get(panel_id, 0)
        )

    def capture_dirty_panel(
        self, panel_id: str
    ) -> tuple[str, bytes, int, int] | None:
        revisions = self.window.panel_manager.panel_refresh_revisions()
        revision = revisions.get(panel_id, 0)
        if (
            panel_id in self._last_panel_frame
            and self._captured_panel_revisions.get(panel_id) == revision
        ):
            return None
        capture_started = time.monotonic()
        image_format, data, width, height = self.capture_panel(panel_id)
        capture_ms = (time.monotonic() - capture_started) * 1000.0
        frame = (image_format, data)
        self._captured_panel_revisions[panel_id] = revision
        changed = frame != self._last_panel_frame.get(panel_id)
        if changed:
            self._last_panel_frame[panel_id] = frame
            self._last_panel_dimensions[panel_id] = (width, height)
        perf_log(
            "notebook_renderer",
            "panel_capture",
            panel_id=panel_id,
            revision=revision,
            format=image_format,
            frame_bytes=len(data),
            changed=changed,
            duration_ms=round(capture_ms, 3),
        )
        if not changed:
            return None
        return (
            image_format,
            data,
            width,
            height,
        )

    def panel_frames(self) -> dict[str, tuple[str, bytes, int, int]]:
        """Return the latest generic raster projection keyed by panel id."""
        frames: dict[str, tuple[str, bytes, int, int]] = {}
        for panel_id, image in self._panel_images.items():
            data = (
                image.latest_frame_data
                if isinstance(image, NotebookRfbWidget)
                else bytes(image.value)
            )
            if data:
                width, height = self._last_panel_dimensions.get(
                    panel_id,
                    (
                        int(getattr(image, "frame_width", image.width)),
                        int(getattr(image, "frame_height", image.height)),
                    ),
                )
                frames[panel_id] = (
                    str(image.format),
                    data,
                    width,
                    height,
                )
        return frames

    def _has_uncaptured_panel_refreshes(self) -> bool:
        if self._external_frames:
            return False
        revisions = self.window.panel_manager.panel_refresh_revisions()
        return any(
            panel_id not in self._last_panel_frame
            or self._captured_panel_revisions.get(panel_id)
            != revisions.get(panel_id, 0)
            for panel_id in self._panel_images
        )

    def capture_panel(self, panel_id: str) -> tuple[str, bytes, int, int]:
        """Capture one panel without inspecting its authored widget kind."""
        lifecycle = self.window.panel_manager.panel_hosts.get(panel_id)
        if lifecycle is None:
            raise KeyError(f"Notebook panel {panel_id!r} is not mounted")
        layout_panel = self.window._active_layout().panel(panel_id)
        if layout_panel is None or self.window.app_spec is None:
            raise KeyError(f"Notebook panel {panel_id!r} has no active specification")
        policy = panel_frame_policy(self.window.app_spec, layout_panel)
        width, height = self._panel_size
        frame_width = max(1, int(round(width * policy.raster_scale)))
        frame_height = max(1, int(round(height * policy.raster_scale)))
        self._configure_capture_surface(panel_id, lifecycle)
        surfaces = getattr(lifecycle, "inspection_surfaces", {})
        surfaces = surfaces() if callable(surfaces) else surfaces
        surfaces = {} if surfaces is None else dict(surfaces)
        snapshot = surfaces.get("notebook_snapshot")
        if callable(snapshot):
            value = snapshot()
            if isinstance(value, bytes):
                image = QtGui.QImage.fromData(value)
                snapshot_width = image.width() if not image.isNull() else width
                snapshot_height = image.height() if not image.isNull() else height
                return "png", value, snapshot_width, snapshot_height
            array = np.asarray(value)
            return (
                "jpeg",
                _array_jpeg(array, quality=policy.jpeg_quality),
                int(array.shape[1]),
                int(array.shape[0]),
            )
        viewport = surfaces.get("viewport")
        canvas = getattr(viewport, "canvas", None)
        render = getattr(canvas, "render", None)
        if callable(render):
            rendered = render(
                size=(frame_width, frame_height),
                alpha=False,
            )
            return (
                "jpeg",
                _array_jpeg(rendered, quality=policy.jpeg_quality),
                frame_width,
                frame_height,
            )
        widget = lifecycle.widget
        widget.ensurePolished()
        image = _render_widget_image(
            widget,
            logical_size=self._panel_size,
            raster_scale=policy.raster_scale,
        )
        return (
            "jpeg",
            _qimage_bytes(
                image,
                image_format="JPEG",
                quality=policy.jpeg_quality,
            ),
            frame_width,
            frame_height,
        )

    def _configure_capture_surface(self, panel_id: str, lifecycle: Any) -> None:
        if self._external_frames:
            return
        if self._capture_surface_lifecycles.get(panel_id) is lifecycle:
            return
        surfaces = getattr(lifecycle, "inspection_surfaces", {})
        surfaces = surfaces() if callable(surfaces) else surfaces
        surfaces = {} if surfaces is None else dict(surfaces)
        viewport = surfaces.get("viewport")
        canvas = getattr(viewport, "canvas", None)
        if canvas is not None:
            # Vispy's render target is expressed in physical pixels, while its
            # native Qt canvas is sized in logical pixels. Keeping both at the
            # physical frame size on a high-DPI screen applies pixel_scale
            # twice, shifting and cropping the scene. QWidget raster capture
            # below intentionally uses logical size instead.
            scale = max(float(canvas.pixel_scale), 0.01)
            logical_size = tuple(
                max(1, int(round(value / scale)))
                for value in self._panel_size
            )
            native = getattr(canvas, "native", None)
            set_fixed_size = getattr(native, "setFixedSize", None)
            if callable(set_fixed_size):
                set_fixed_size(*logical_size)
            canvas.size = logical_size
            canvas.on_resize(None)
        else:
            widget = lifecycle.widget
            widget.setFixedSize(*self._panel_size)
            widget.ensurePolished()
        self._qapp.processEvents()
        self._capture_surface_lifecycles[panel_id] = lifecycle

    def _structure(self) -> Any:
        if self.window.app_spec is None:
            return None
        layout = self.window._active_layout()

        def panel_signature(panel):
            controls, actions = self.window._resolved_controls_and_actions(panel.id)
            return (
                panel.id,
                panel.kind,
                tuple(panel.view_ids),
                tuple(panel.control_ids),
                tuple(panel.action_ids),
                tuple(panel.contribution_ids),
                panel.title,
                tuple((item.ref, item.spec) for item in controls),
                tuple((item.ref, item.spec) for item in actions),
            )

        return (
            tuple(tuple(row) for row in layout.panel_grid),
            tuple(panel_signature(panel) for panel in layout.panels),
        )

    def _sync_structure(self, *, force: bool = False) -> None:
        signature = self._structure()
        if signature is None or (not force and signature == self._structure_signature):
            return
        self._structure_signature = signature
        self._rebuild_widget_tree()
        self._maybe_begin_execution()
        if not self._external_frames:
            for panel_id, lifecycle in self.window.panel_manager.panel_hosts.items():
                self._configure_capture_surface(panel_id, lifecycle)

    def _rebuild_widget_tree(self) -> None:
        widgets = self._widgets
        layout = self.window._active_layout()
        self._panel_images.clear()
        self._last_panel_frame.clear()
        self._last_panel_dimensions.clear()
        self._captured_panel_revisions.clear()
        self._capture_surface_lifecycles.clear()
        self._presented_external_frames.clear()
        self._capture_cursor = 0
        self._control_bindings.clear()
        rows = []
        for row in layout.panel_grid:
            cells = [self._build_panel_widget(panel_id) for panel_id in row]
            rows.append(
                cells[0]
                if len(cells) == 1
                else widgets.HBox(
                    cells,
                    layout=widgets.Layout(
                        width="100%",
                        align_items="stretch",
                    ),
                )
            )
        self.widget.children = tuple([*rows, self._stop_button])
        for frame in self._pending_external_frames.values():
            self._apply_external_frame(frame)
        self._sync_control_values()
        self._render_due = not self._external_frames

    def _build_panel_widget(self, panel_id: str) -> Any:
        widgets = self._widgets
        panel = self.window._active_layout().panel(panel_id)
        if panel is None:
            raise KeyError(f"Notebook layout references unknown panel {panel_id!r}")
        children: list[Any] = []
        title = panel.title
        if title is None and panel.view_ids:
            view = self.window.app_spec.view(panel.view_ids[0])
            title = getattr(view, "title", None)
        title = title or panel.id
        children.append(widgets.HTML(value=f"<b>{html.escape(str(title))}</b>"))
        controls, actions = self.window._resolved_controls_and_actions(panel_id)
        has_raster_content = bool(
            panel.view_ids or panel.contribution_ids or not (controls or actions)
        )
        if has_raster_content:
            if self._external_frames:
                image = NotebookRfbWidget(
                    width=self._panel_size[0],
                    height=self._panel_size[1],
                )
                image.on_presented(
                    lambda sequence, _panel_id=panel_id: self._on_frame_presented(
                        _panel_id, sequence
                    )
                )
            else:
                image = widgets.Image(
                    format="jpeg",
                    width=self._panel_size[0],
                    height=self._panel_size[1],
                )
            self._panel_images[panel_id] = image
            children.append(image)
        children.extend(self._build_controls(controls))
        children.extend(self._build_actions(actions))
        return widgets.VBox(
            children,
            layout=widgets.Layout(
                width="100%",
                border="1px solid #888",
                padding="4px",
            ),
        )

    def _apply_external_frame(
        self,
        frame: RenderedFrame,
        *,
        tags: Any = None,
    ) -> None:
        started = time.monotonic()
        image = self._panel_images.get(frame.frame_id)
        if image is None:
            return
        presented = (
            frame.format,
            frame.data,
            frame.width,
            frame.height,
        )
        if self._presented_external_frames.get(frame.frame_id) == presented:
            return
        if isinstance(image, NotebookRfbWidget):
            image.send_frame(
                frame.data,
                sequence=frame.sequence,
                image_format=frame.format,
                width=frame.width,
                height=frame.height,
            )
        else:
            with image.hold_sync():
                image.format = frame.format
                image.value = frame.data
        if frame.width is not None and frame.height is not None:
            self._last_panel_dimensions[frame.frame_id] = (
                int(frame.width),
                int(frame.height),
            )
        self._presented_external_frames[frame.frame_id] = presented
        apply_ms = (time.monotonic() - started) * 1000.0
        self._record_frame_apply(frame, apply_ms=apply_ms, tags=tags or {})

    def _on_frame_presented(self, panel_id: str, sequence: int) -> None:
        self.emit_command(FramePresented(panel_id, int(sequence)))
        self._maybe_begin_execution()

    def _maybe_begin_execution(self) -> None:
        if (
            self._execution_begun
            or self.window.app_spec is None
            or not self._begin_on_first_paint
        ):
            return
        raster_panels = tuple(
            image
            for image in self._panel_images.values()
            if isinstance(image, NotebookRfbWidget)
        )
        if raster_panels and not all(image._ack >= 1 for image in raster_panels):
            return
        self._execution_begun = True
        self.emit_command(BeginExecution())

    def _record_frame_apply(
        self,
        frame: RenderedFrame,
        *,
        apply_ms: float,
        tags: Any,
    ) -> None:
        now = time.monotonic()
        self._perf_frame_count += 1
        self._perf_frame_bytes += len(frame.data)
        self._perf_frame_apply_ms += apply_ms
        self._perf_frame_apply_ms_max = max(
            self._perf_frame_apply_ms_max, apply_ms
        )
        trace_id = tags.get("perf_trace_id")
        control_started = tags.get("perf_control_mono_s")
        if trace_id is not None:
            perf_log(
                "notebook_frontend",
                "traced_frame_applied",
                trace_id=trace_id,
                panel_id=frame.frame_id,
                frame_bytes=len(frame.data),
                apply_ms=round(apply_ms, 3),
                control_to_frame_ms=(
                    round((now - float(control_started)) * 1000.0, 3)
                    if control_started is not None
                    else None
                ),
            )
        elapsed_s = now - self._perf_frame_window_started
        if elapsed_s < 1.0:
            return
        perf_log(
            "notebook_frontend",
            "frame_apply_window",
            window_s=round(elapsed_s, 3),
            frame_count=self._perf_frame_count,
            frame_hz=round(self._perf_frame_count / elapsed_s, 3),
            frame_bytes=self._perf_frame_bytes,
            frame_mib_s=round(
                self._perf_frame_bytes / elapsed_s / (1024.0 * 1024.0), 3
            ),
            apply_ms_total=round(self._perf_frame_apply_ms, 3),
            apply_ms_avg=round(
                self._perf_frame_apply_ms / max(self._perf_frame_count, 1), 3
            ),
            apply_ms_max=round(self._perf_frame_apply_ms_max, 3),
        )
        self._perf_frame_window_started = now
        self._perf_frame_count = 0
        self._perf_frame_bytes = 0
        self._perf_frame_apply_ms = 0.0
        self._perf_frame_apply_ms_max = 0.0

    def _build_controls(
        self, controls: list[ResolvedControl]
    ) -> list[Any]:
        rendered = []
        values = self.window.value_snapshot()
        for resolved in controls:
            holder: dict[str, _ControlBinding] = {}

            def emit(value: Any, *, _holder=holder) -> None:
                binding = _holder["binding"]
                if binding.syncing:
                    return
                started = time.monotonic()
                trace_tags = None
                if perf_logging_enabled():
                    self._perf_trace_sequence += 1
                    trace_tags = {
                        "perf_trace_id": (
                            f"control-{time.monotonic_ns()}-"
                            f"{self._perf_trace_sequence}"
                        ),
                        "perf_control_mono_s": started,
                    }
                self.window._on_control_changed(binding.resolved, value)
                self._drain_window_messages(extra_tags=trace_tags)
                self._render_due = True
                perf_log(
                    "notebook_frontend",
                    "control_dispatched",
                    trace_id=(
                        trace_tags["perf_trace_id"]
                        if trace_tags is not None
                        else None
                    ),
                    control_id=str(binding.resolved.ref),
                    value=value,
                    duration_ms=round(
                        (time.monotonic() - started) * 1000.0, 3
                    ),
                )

            context = NotebookControlRenderContext(emit)
            current = values.get(
                resolved.value_ref,
                resolved.spec.default_value(),
            )
            presentation = control_renderer(
                resolved.spec.presentation.kind
            )(context, resolved.spec, current)
            if not isinstance(presentation, NotebookControlPresentation):
                raise TypeError(
                    f"Notebook control renderer {resolved.spec.presentation.kind!r} "
                    "must return NotebookControlPresentation"
                )
            if not isinstance(presentation.widget, self._widgets.Widget):
                raise TypeError(
                    f"Notebook control renderer {resolved.spec.presentation.kind!r} "
                    "must expose an ipywidgets Widget"
                )
            binding = _ControlBinding(resolved, presentation)
            holder["binding"] = binding
            self._control_bindings[resolved.ref] = binding
            rendered.append(presentation.widget)
        return rendered

    def _build_actions(self, actions: list[ResolvedAction]) -> list[Any]:
        rendered = []
        for resolved in actions:
            context = NotebookActionRenderContext(
                lambda item=resolved: self._invoke_action(item)
            )
            widget = action_renderer(resolved.spec.presentation_kind)(
                context,
                resolved.spec,
                self.window.value_snapshot(),
            )
            if not isinstance(widget, self._widgets.Widget):
                raise TypeError(
                    f"Notebook action renderer {resolved.spec.presentation_kind!r} "
                    "must return an ipywidgets Widget"
                )
            rendered.append(widget)
        return rendered

    def _invoke_action(self, action: ResolvedAction) -> None:
        values = self.window.value_snapshot()
        payload = {
            key: resolve_binding(value, values, action.ref.fragment_id)
            for key, value in action.spec.payload.items()
        }
        self.window._on_action_invoked(action, payload)
        self._drain_window_messages()
        self._render_due = True

    def _sync_control_values(self) -> None:
        values = self.window.value_snapshot()
        for binding in self._control_bindings.values():
            value = values.get(
                binding.resolved.value_ref,
                binding.resolved.spec.default_value(),
            )
            binding.syncing = True
            try:
                binding.presentation.set_value(value)
            finally:
                binding.syncing = False

    def _drain_window_messages(self, *, extra_tags: Any = None) -> None:
        for message in self.window.take_outbound_messages():
            if extra_tags:
                message = type(message)(
                    type=message.type,
                    intent=message.intent,
                    payload=message.payload,
                    tags={**message.tags, **extra_tags},
                )
            self.emit(message)


__all__ = ["NotebookFrontend"]
