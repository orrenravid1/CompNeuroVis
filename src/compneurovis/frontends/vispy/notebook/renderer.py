"""Generic out-of-kernel raster renderer for notebook panels."""

from __future__ import annotations

from collections import deque
import time

from compneurovis.core import AppSpec
from compneurovis.core.messages import (
    FramePresented,
    Message,
    MessagePayload,
    RenderedFrame,
)
from compneurovis.frontends.base import FrontendBase
from compneurovis.frontends.vispy.notebook.frontend import NotebookFrontend
from compneurovis.frontends.vispy.notebook.registries import panel_frame_policy
from compneurovis.core.runtime.performance import perf_log


class NotebookPanelRenderActor(FrontendBase):
    """Render the registered panel graph and emit latest panel frames.

    Browser paint acknowledgements bound frame production. Authored widget kinds
    stay inside registered lifecycles; scheduling sees only panel ids and frame
    policies registered against neutral view kinds.
    """

    def __init__(
        self,
        *,
        render_hz: float = 15.0,
        panel_size: tuple[int, int] = (960, 540),
        max_inflight_frames: int = 3,
    ) -> None:
        super().__init__()
        self._render_hz = max(float(render_hz), 1.0)
        self._panel_size = panel_size
        self._max_inflight_frames = max(1, int(max_inflight_frames))
        self._frontend: NotebookFrontend | None = None
        self._pending_messages: deque[Message[MessagePayload]] = deque()
        self._mounted_panels: set[str] = set()
        self._inflight_sequences: dict[str, deque[int]] = {}
        self._next_sequences: dict[str, int] = {}
        self._last_emitted_at: dict[str, float] = {}
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
            automatic_capture=False,
        )
        self._frontend.initialize(app_spec)
        perf_log(
            "notebook_renderer",
            "initialize",
            panel_count=len(self._frontend.panel_ids()),
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
            render_messages = []
            for message in messages:
                if isinstance(message.payload, FramePresented):
                    self._acknowledge_frame(message.payload)
                    continue
                render_messages.append(message)
                if message.tags.get("perf_trace_id") is not None:
                    trace_id = message.tags["perf_trace_id"]
                    control_started = message.tags.get("perf_control_mono_s")
            handle_started = time.monotonic()
            frontend.handle_messages(render_messages)
            handle_ms = (time.monotonic() - handle_started) * 1000.0
        tick_started = time.monotonic()
        frontend.tick()
        tick_ms = (time.monotonic() - tick_started) * 1000.0
        emitted_panel_ids, emitted_bytes = self._emit_credited_frames(frontend)
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

    def _acknowledge_frame(self, acknowledgment: FramePresented) -> None:
        panel_id = acknowledgment.frame_id
        self._mounted_panels.add(panel_id)
        inflight = self._inflight_sequences.get(panel_id)
        if inflight is not None:
            while inflight and inflight[0] <= acknowledgment.sequence:
                inflight.popleft()
            if not inflight:
                self._inflight_sequences.pop(panel_id, None)
        perf_log(
            "notebook_renderer",
            "frame_presented",
            panel_id=panel_id,
            sequence=acknowledgment.sequence,
            inflight_count=self._inflight_count(),
        )

    def _inflight_count(self) -> int:
        return sum(len(sequences) for sequences in self._inflight_sequences.values())

    def _emit_credited_frames(
        self, frontend: NotebookFrontend
    ) -> tuple[list[str], int]:
        active_panel_ids = set(frontend.panel_ids())
        for panel_id in tuple(self._inflight_sequences):
            if panel_id not in active_panel_ids:
                self._inflight_sequences.pop(panel_id, None)
        self._mounted_panels.intersection_update(active_panel_ids)

        available_slots = self._max_inflight_frames - self._inflight_count()
        if available_slots <= 0 or frontend.app_spec is None:
            return [], 0

        now = time.monotonic()
        layout = frontend.window._active_layout()
        candidates = []
        for panel_id in frontend.dirty_panel_ids():
            if panel_id not in self._mounted_panels:
                continue
            panel = layout.panel(panel_id)
            if panel is None:
                continue
            policy = panel_frame_policy(frontend.app_spec, panel)
            if len(self._inflight_sequences.get(panel_id, ())) >= policy.max_inflight:
                continue
            target_hz = min(policy.target_hz, self._render_hz)
            deadline = self._last_emitted_at.get(panel_id, 0.0) + 1.0 / target_hz
            if now < deadline:
                continue
            candidates.append((deadline, -policy.priority, panel_id, policy))
        candidates.sort()

        emitted_panel_ids: list[str] = []
        emitted_bytes = 0
        for _, _, panel_id, _ in candidates[:available_slots]:
            captured = frontend.capture_dirty_panel(panel_id)
            self._last_emitted_at[panel_id] = now
            if captured is None:
                continue
            image_format, data, width, height = captured
            sequence = self._next_sequences.get(panel_id, 0) + 1
            self._next_sequences[panel_id] = sequence
            self._inflight_sequences.setdefault(panel_id, deque()).append(sequence)
            emitted_panel_ids.append(panel_id)
            emitted_bytes += len(data)
            self.emit_update(
                RenderedFrame(
                    frame_id=panel_id,
                    data=data,
                    format=image_format,
                    width=width,
                    height=height,
                    sequence=sequence,
                )
            )
        return emitted_panel_ids, emitted_bytes

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
            inflight_count=self._inflight_count(),
            mounted_panel_count=len(self._mounted_panels),
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
        return min(1.0 / self._render_hz, 1.0 / 30.0)

    def shutdown(self) -> None:
        if self._frontend is not None:
            self._frontend.shutdown()
            self._frontend = None

    def _require_frontend(self) -> NotebookFrontend:
        if self._frontend is None:
            raise RuntimeError("NotebookPanelRenderActor is not initialized")
        return self._frontend


__all__ = ["NotebookPanelRenderActor"]
