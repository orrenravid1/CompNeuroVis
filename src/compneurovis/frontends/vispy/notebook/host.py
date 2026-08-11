"""Async notebook actor host for the generic notebook frontend."""

from __future__ import annotations

import asyncio
import time
import traceback
from typing import Any

from compneurovis.core.messages import StopActor
from compneurovis.core.runtime import AppRuntime
from compneurovis.core.runtime.actor_host import ActorHost
from compneurovis.core.runtime.channel import Channel
from compneurovis.core.runtime.performance import perf_log
from compneurovis.frontends.vispy.notebook.frontend import NotebookFrontend


POLL_HZ = 30.0


class NotebookActorHost(ActorHost):
    """Drive notebook transport polling without owning widget-specific logic."""

    def __init__(
        self,
        runtime: AppRuntime,
        channel: Channel,
        *,
        render_hz: float = 30.0,
        panel_size: tuple[int, int] = (960, 540),
        external_frames: bool = False,
        begin_on_first_paint: bool = False,
    ) -> None:
        super().__init__(channel=channel)
        self._runtime = runtime
        self._render_hz = float(render_hz)
        self._panel_size = panel_size
        self._external_frames = bool(external_frames)
        self._begin_on_first_paint = bool(begin_on_first_paint)
        self._running = False
        self._stopped = False
        self._app_handle = None
        self._task: asyncio.Task | None = None
        self._perf_poll_window_started = time.monotonic()
        self._perf_poll_count = 0
        self._perf_poll_gap_ms_total = 0.0
        self._perf_poll_gap_ms_max = 0.0
        self._perf_poll_step_ms_total = 0.0
        self._perf_poll_step_ms_max = 0.0

    def bind_app_handle(self, handle: Any) -> None:
        self._app_handle = handle

    def start(self) -> None:
        super().start(
            lambda: NotebookFrontend(
                render_hz=self._render_hz,
                panel_size=self._panel_size,
                external_frames=self._external_frames,
                begin_on_first_paint=self._begin_on_first_paint,
            ),
            self._runtime.app_spec,
        )
        self._running = True

    def run(self) -> Any:
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._poll_loop())
        return self._notebook_frontend().widget

    def receive(self) -> None:
        if self.channel is None:
            return
        messages = []
        for message in self.channel.poll():
            if isinstance(message.payload, StopActor):
                self._stop_requested = True
                self.stop()
                return
            messages.append(message)
        self._notebook_frontend().handle_messages(messages)

    def stop(self) -> None:
        if self._stopped:
            return
        if (
            self._app_handle is not None
            and not getattr(self._app_handle, "_stopping", False)
        ):
            self._app_handle.stop()
            return
        self._stopped = True
        self._running = False
        if self._task is not None:
            self._task.cancel()
            self._task = None
        self._runtime.stop()
        super().stop()

    async def _poll_loop(self) -> None:
        interval = 1.0 / POLL_HZ
        perf_log("notebook_frontend", "poll_loop_start")
        previous_started = time.monotonic()
        while self._running:
            if self._notebook_frontend().stop_requested:
                self.stop()
                break
            try:
                started = time.monotonic()
                gap_ms = (started - previous_started) * 1000.0
                self.step()
                step_ms = (time.monotonic() - started) * 1000.0
                previous_started = started
                self._record_poll_perf(gap_ms=gap_ms, step_ms=step_ms)
            except (BrokenPipeError, OSError):
                perf_log("notebook_frontend", "poll_loop_transport_closed")
                self._running = False
                break
            except Exception as exc:
                perf_log(
                    "notebook_frontend",
                    "poll_loop_error",
                    error_type=type(exc).__name__,
                    message=str(exc),
                    traceback="".join(traceback.format_exception(exc)),
                )
                self._running = False
                raise
            await asyncio.sleep(interval)
        perf_log("notebook_frontend", "poll_loop_end", running=self._running)

    def _record_poll_perf(self, *, gap_ms: float, step_ms: float) -> None:
        self._perf_poll_count += 1
        self._perf_poll_gap_ms_total += gap_ms
        self._perf_poll_gap_ms_max = max(self._perf_poll_gap_ms_max, gap_ms)
        self._perf_poll_step_ms_total += step_ms
        self._perf_poll_step_ms_max = max(self._perf_poll_step_ms_max, step_ms)
        now = time.monotonic()
        elapsed_s = now - self._perf_poll_window_started
        if elapsed_s < 1.0:
            return
        count = self._perf_poll_count
        perf_log(
            "notebook_frontend",
            "poll_window",
            window_s=round(elapsed_s, 3),
            poll_count=count,
            poll_hz=round(count / elapsed_s, 3),
            poll_gap_ms_avg=round(self._perf_poll_gap_ms_total / count, 3),
            poll_gap_ms_max=round(self._perf_poll_gap_ms_max, 3),
            poll_step_ms_avg=round(self._perf_poll_step_ms_total / count, 3),
            poll_step_ms_max=round(self._perf_poll_step_ms_max, 3),
        )
        self._perf_poll_window_started = now
        self._perf_poll_count = 0
        self._perf_poll_gap_ms_total = 0.0
        self._perf_poll_gap_ms_max = 0.0
        self._perf_poll_step_ms_total = 0.0
        self._perf_poll_step_ms_max = 0.0

    def _notebook_frontend(self) -> NotebookFrontend:
        actor = self._actor()
        if not isinstance(actor, NotebookFrontend):
            raise TypeError(
                f"NotebookActorHost expected NotebookFrontend, got {type(actor)!r}"
            )
        return actor


__all__ = ["NotebookActorHost"]
