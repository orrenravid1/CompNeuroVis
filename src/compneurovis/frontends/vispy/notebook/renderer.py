"""Generic out-of-kernel raster renderer for notebook panels."""

from __future__ import annotations

from collections import deque
import time

from compneurovis.core import AppSpec
from compneurovis.core.messages import Message, MessagePayload, RenderedFrame
from compneurovis.frontends.base import FrontendBase
from compneurovis.frontends.vispy.notebook.frontend import NotebookFrontend
from compneurovis.core.runtime.performance import perf_log


class NotebookPanelRenderActor(FrontendBase):
    """Render the registered panel graph and emit latest panel frames.

    This actor knows panel ids and raster frames only. Authored widget kinds stay
    inside their registered Vispy lifecycles.
    """

    def __init__(
        self,
        *,
        render_hz: float = 8.0,
        panel_size: tuple[int, int] = (960, 540),
    ) -> None:
        super().__init__()
        self._render_hz = render_hz
        self._panel_size = panel_size
        self._frontend: NotebookFrontend | None = None
        self._pending_messages: deque[Message[MessagePayload]] = deque()
        self._emitted_frames: dict[str, tuple[str, bytes]] = {}
        self._perf_window_started = time.monotonic()
        self._perf_message_count = 0
        self._perf_handle_ms = 0.0
        self._perf_tick_ms = 0.0
        self._perf_frame_count = 0
        self._perf_frame_bytes = 0

    def initialize(self, app_spec: AppSpec | None) -> None:
        started = time.monotonic()
        self._frontend = NotebookFrontend(
            render_hz=self._render_hz,
            panel_size=self._panel_size,
            panel_capture_budget=1,
        )
        self._frontend.initialize(app_spec)
        perf_log(
            "notebook_renderer",
            "initialize",
            panel_count=len(self._frontend.panel_frames()),
            duration_ms=round((time.monotonic() - started) * 1000.0, 3),
        )

    def handle(self, message: Message[MessagePayload]) -> None:
        self._pending_messages.append(message)

    def tick(self) -> None:
        frontend = self._require_frontend()
        message_count = 0
        handle_ms = 0.0
        trace_id = None
        control_started = None
        if self._pending_messages:
            messages = list(self._pending_messages)
            self._pending_messages.clear()
            message_count = len(messages)
            for message in messages:
                if message.tags.get("perf_trace_id") is not None:
                    trace_id = message.tags["perf_trace_id"]
                    control_started = message.tags.get("perf_control_mono_s")
            handle_started = time.monotonic()
            frontend.handle_messages(messages)
            handle_ms = (time.monotonic() - handle_started) * 1000.0
        tick_started = time.monotonic()
        frontend.tick()
        tick_ms = (time.monotonic() - tick_started) * 1000.0
        emitted_panel_ids = []
        emitted_bytes = 0
        for panel_id, (image_format, data, width, height) in (
            frontend.panel_frames().items()
        ):
            frame = (image_format, data)
            if self._emitted_frames.get(panel_id) == frame:
                continue
            self._emitted_frames[panel_id] = frame
            emitted_panel_ids.append(panel_id)
            emitted_bytes += len(data)
            self.emit_update(
                RenderedFrame(
                    frame_id=panel_id,
                    data=frame[1],
                    format=frame[0],
                    width=width,
                    height=height,
                )
            )
        self._record_perf_window(
            message_count=message_count,
            handle_ms=handle_ms,
            tick_ms=tick_ms,
            frame_count=len(emitted_panel_ids),
            frame_bytes=emitted_bytes,
        )
        if trace_id is not None:
            perf_log(
                "notebook_renderer",
                "traced_render",
                trace_id=trace_id,
                input_message_count=message_count,
                emitted_panel_ids=emitted_panel_ids,
                emitted_frame_bytes=emitted_bytes,
                handle_ms=round(handle_ms, 3),
                tick_ms=round(tick_ms, 3),
                control_to_render_ms=(
                    round(
                        (time.monotonic() - float(control_started)) * 1000.0,
                        3,
                    )
                    if control_started is not None
                    else None
                ),
            )

    def _record_perf_window(
        self,
        *,
        message_count: int,
        handle_ms: float,
        tick_ms: float,
        frame_count: int,
        frame_bytes: int,
    ) -> None:
        self._perf_message_count += message_count
        self._perf_handle_ms += handle_ms
        self._perf_tick_ms += tick_ms
        self._perf_frame_count += frame_count
        self._perf_frame_bytes += frame_bytes
        now = time.monotonic()
        elapsed_s = now - self._perf_window_started
        if elapsed_s < 1.0:
            return
        perf_log(
            "notebook_renderer",
            "render_window",
            window_s=round(elapsed_s, 3),
            input_message_count=self._perf_message_count,
            handle_ms_total=round(self._perf_handle_ms, 3),
            frontend_tick_ms_total=round(self._perf_tick_ms, 3),
            frame_count=self._perf_frame_count,
            frame_hz=round(self._perf_frame_count / elapsed_s, 3),
            frame_bytes=self._perf_frame_bytes,
            frame_mib_s=round(
                self._perf_frame_bytes / elapsed_s / (1024.0 * 1024.0), 3
            ),
        )
        self._perf_window_started = now
        self._perf_message_count = 0
        self._perf_handle_ms = 0.0
        self._perf_tick_ms = 0.0
        self._perf_frame_count = 0
        self._perf_frame_bytes = 0

    def is_active(self) -> bool:
        return True

    def idle_sleep(self) -> float:
        return min(1.0 / max(float(self._render_hz), 1.0), 1.0 / 30.0)

    def shutdown(self) -> None:
        if self._frontend is not None:
            self._frontend.shutdown()
            self._frontend = None

    def _require_frontend(self) -> NotebookFrontend:
        if self._frontend is None:
            raise RuntimeError("NotebookPanelRenderActor is not initialized")
        return self._frontend


__all__ = ["NotebookPanelRenderActor"]
