from __future__ import annotations

from collections import deque
import signal
import sys
import threading
import time

from PyQt6 import QtCore, QtGui, QtWidgets
from vispy import app as vispy_app

from compneurovis.core.runtime.performance import perf_log
from compneurovis.core.runtime.options import env_int
from compneurovis.core.runtime.actor import ActorSource
from compneurovis.core.runtime.channel import Channel
from compneurovis.core.runtime.actor_host import ActorHost
from compneurovis.core.messages import Message, MessagePayload, StopActor
from compneurovis.core.runtime import AppRuntime
from compneurovis.frontends.vispy.frontend import VispyFrontendWindow

# Qt's event loop must run in the main process and main thread: a VisPy/Qt
# constraint, not a generic architectural one. Non-Qt actors can use the
# ordinary ActorProcess path.

FRONTEND_TIMER_INTERVAL_MS = 1000 // 60
FRONTEND_STEP_SOFT_BUDGET_S = env_int("CNV_FRONTEND_STEP_SOFT_BUDGET_MS", 12, minimum=1) / 1000.0
FRONTEND_MAX_INBOUND_MESSAGES_PER_STEP = 64
FRONTEND_BACKLOG_COMPACT_THRESHOLD = 128
FRONTEND_TIMER_GAP_HICCUP_MS = 50.0
FRONTEND_STEP_HICCUP_MS = 24.0
FRONTEND_PHASE_HICCUP_MS = 8.0


def _configure_vispy_backend() -> None:
    """Select the desktop backend only when a desktop host actually starts."""

    from vispy import use

    use(app="pyqt6", gl="gl+")


def _configure_qt_surface_format() -> tuple[QtGui.QSurfaceFormat, QtGui.QSurfaceFormat]:
    """Request immediate GL buffer swaps for VisPy/Qt canvases.

    VisPy's per-canvas ``vsync=False`` is not always enough on Qt/PyQt6. Qt's
    default surface format is copied when native GL widgets are created, so set
    the swap interval before QApplication/window/canvas construction.
    """

    before = QtGui.QSurfaceFormat.defaultFormat()
    fmt = QtGui.QSurfaceFormat(before)
    fmt.setSwapInterval(0)
    QtGui.QSurfaceFormat.setDefaultFormat(fmt)
    after = QtGui.QSurfaceFormat.defaultFormat()
    perf_log(
        "frontend",
        "qt_surface_format",
        swap_interval_before=int(before.swapInterval()),
        swap_interval_after=int(after.swapInterval()),
        qapp_exists=QtWidgets.QApplication.instance() is not None,
    )
    return before, after


class VispyActorHost(ActorHost):
    def __init__(
        self,
        actor_source: ActorSource,
        runtime: AppRuntime,
        channel: Channel | None = None,
    ) -> None:
        super().__init__(channel=channel)
        self._actor_source = actor_source
        self._runtime = runtime
        self._qapp: QtWidgets.QApplication | None = None
        self.timer: QtCore.QTimer | None = None
        self._last_step_started_s: float | None = None
        self._inbound_messages: deque[Message[MessagePayload]] = deque()
        self._sigint_handler = None
        self._previous_sigint_handler = None
        self._owned_qt_surface_format: QtGui.QSurfaceFormat | None = None
        self._previous_qt_surface_format: QtGui.QSurfaceFormat | None = None

    def start(self) -> None:
        _configure_vispy_backend()
        (
            self._previous_qt_surface_format,
            self._owned_qt_surface_format,
        ) = _configure_qt_surface_format()
        if QtWidgets.QApplication.instance() is None:
            self._qapp = QtWidgets.QApplication(sys.argv)
        else:
            self._qapp = QtWidgets.QApplication.instance()
        self._install_sigint_handler()
        window = super().start(self._actor_source, self._runtime.app_spec)
        assert isinstance(window, VispyFrontendWindow)
        self.timer = QtCore.QTimer(window)
        self.timer.timeout.connect(self.step)
        self.timer.start(FRONTEND_TIMER_INTERVAL_MS)
        window.show()
        # Backend/model construction already runs in its own process. Resolve
        # frontend capabilities after the loading window is shown so this cold
        # import work overlaps that independent startup instead of extending the
        # critical path after AppSpec arrival.
        QtCore.QTimer.singleShot(0, window.preload_plugins)

    def run(self) -> None:
        vispy_app.run()

    def step(self) -> None:
        if self.actor is None:
            return
        window = self._window()
        started = time.monotonic()
        timer_gap_ms = (
            None if self._last_step_started_s is None
            else round((started - self._last_step_started_s) * 1000.0, 3)
        )
        self._last_step_started_s = started
        inbound_before_poll_count = len(self._inbound_messages)
        inbound_after_poll_count = inbound_before_poll_count
        inbound_after_compact_count = inbound_before_poll_count
        inbound_after_drain_count = inbound_before_poll_count
        poll_message_count = 0
        poll_payload_count = None
        poll_truncated = None
        poll_more_pending = None
        compacted_before_count = None
        compacted_after_count = None
        outbound_before_count = 0
        outbound_after_count = 0
        drained_count = 0
        poll_ms = 0.0
        compact_ms = 0.0
        drain_ms = 0.0
        handle_ms = 0.0
        refresh_ms = 0.0
        if self.channel is not None:
            outbound_before_count = self._flush_outbound(window)
            poll_started = time.monotonic()
            messages = self.channel.poll()
            poll_ms = round((time.monotonic() - poll_started) * 1000.0, 3)
            poll_message_count = len(messages)
            poll_payload_count = getattr(self.channel, "last_payload_count", None)
            poll_truncated = getattr(self.channel, "last_poll_truncated", None)
            poll_more_pending = getattr(self.channel, "last_more_pending", None)
            for message in messages:
                if isinstance(message.payload, StopActor):
                    self._stop_requested = True
                    self._runtime.stop()
                    if self._qapp is not None:
                        self._qapp.quit()
                    return
            self._inbound_messages.extend(messages)
            inbound_after_poll_count = len(self._inbound_messages)
            inbound_after_compact_count = inbound_after_poll_count
            if (
                len(self._inbound_messages) >= FRONTEND_BACKLOG_COMPACT_THRESHOLD
                and window.app_projection is not None
            ):
                compact_started = time.monotonic()
                before_count = len(self._inbound_messages)
                compacted = window.compact_update_messages(list(self._inbound_messages))
                self._inbound_messages = deque(compacted)
                compact_ms = round((time.monotonic() - compact_started) * 1000.0, 3)
                compacted_before_count = before_count
                compacted_after_count = len(self._inbound_messages)
                inbound_after_compact_count = len(self._inbound_messages)
                perf_log(
                    "frontend",
                    "compact_inbound_backlog",
                    before_count=before_count,
                    after_count=len(self._inbound_messages),
                    duration_ms=compact_ms,
                )
            drain_started = time.monotonic()
            batch = self._drain_inbound_messages(started + FRONTEND_STEP_SOFT_BUDGET_S)
            drain_ms = round((time.monotonic() - drain_started) * 1000.0, 3)
            drained_count = len(batch)
            inbound_after_drain_count = len(self._inbound_messages)
            if batch:
                handle_started = time.monotonic()
                window._handle_update_messages(
                    batch,
                    poll_started=started,
                    timer_gap_ms=timer_gap_ms,
                    refresh_deadline_s=started + FRONTEND_STEP_SOFT_BUDGET_S,
                )
                handle_ms = round((time.monotonic() - handle_started) * 1000.0, 3)
            outbound_after_count = self._flush_outbound(window)
        elapsed_s = time.monotonic() - started
        if elapsed_s < FRONTEND_STEP_SOFT_BUDGET_S:
            refresh_started = time.monotonic()
            window.flush_due_refreshes(
                now=started,
                refresh_deadline_s=started + FRONTEND_STEP_SOFT_BUDGET_S,
            )
            refresh_ms = round((time.monotonic() - refresh_started) * 1000.0, 3)
        else:
            elapsed_ms_for_defer = round(elapsed_s * 1000.0, 3)
            if self._inbound_messages or elapsed_ms_for_defer >= FRONTEND_STEP_HICCUP_MS:
                perf_log(
                    "frontend",
                    "defer_due_refreshes",
                    elapsed_ms=elapsed_ms_for_defer,
                    budget_ms=round(FRONTEND_STEP_SOFT_BUDGET_S * 1000.0, 3),
                    inbound_backlog_count=len(self._inbound_messages),
                )
        elapsed_ms = round((time.monotonic() - started) * 1000.0, 3)
        timer_gap_hiccup = timer_gap_ms is not None and timer_gap_ms >= FRONTEND_TIMER_GAP_HICCUP_MS
        step_hiccup = elapsed_ms >= FRONTEND_STEP_HICCUP_MS
        phase_hiccup = max(poll_ms, compact_ms, drain_ms, handle_ms, refresh_ms) >= FRONTEND_PHASE_HICCUP_MS
        backlog_hiccup = inbound_after_drain_count > 0 or bool(poll_truncated) or bool(poll_more_pending)
        if timer_gap_hiccup or step_hiccup or phase_hiccup or backlog_hiccup:
            perf_log(
                "frontend",
                "step_hiccup",
                elapsed_ms=elapsed_ms,
                budget_ms=round(FRONTEND_STEP_SOFT_BUDGET_S * 1000.0, 3),
                timer_gap_ms=timer_gap_ms,
                poll_ms=poll_ms,
                compact_ms=compact_ms,
                drain_ms=drain_ms,
                handle_ms=handle_ms,
                refresh_ms=refresh_ms,
                inbound_before_poll_count=inbound_before_poll_count,
                inbound_after_poll_count=inbound_after_poll_count,
                inbound_after_compact_count=inbound_after_compact_count,
                inbound_after_drain_count=inbound_after_drain_count,
                poll_message_count=poll_message_count,
                poll_payload_count=poll_payload_count,
                poll_truncated=poll_truncated,
                poll_more_pending=poll_more_pending,
                drained_count=drained_count,
                compacted_before_count=compacted_before_count,
                compacted_after_count=compacted_after_count,
                outbound_before_count=outbound_before_count,
                outbound_after_count=outbound_after_count,
                timer_gap_hiccup=timer_gap_hiccup,
                step_hiccup=step_hiccup,
                phase_hiccup=phase_hiccup,
                backlog_hiccup=backlog_hiccup,
            )

    def stop(self) -> None:
        errors: list[Exception] = []
        if self.timer is not None:
            try:
                self.timer.stop()
            except Exception as exc:
                errors.append(exc)
            finally:
                self.timer = None
        try:
            super().stop()
        except Exception as exc:
            errors.append(exc)
        try:
            self._restore_sigint_handler()
        except Exception as exc:
            errors.append(exc)
        try:
            self._restore_qt_surface_format()
        except Exception as exc:
            errors.append(exc)
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise ExceptionGroup("CompNeuroVis VisPy cleanup failed", errors)

    def _install_sigint_handler(self) -> None:
        if threading.current_thread() is not threading.main_thread():
            return
        self._previous_sigint_handler = signal.getsignal(signal.SIGINT)

        def quit_qapp(*_args) -> None:
            if self._qapp is not None:
                self._qapp.quit()

        self._sigint_handler = quit_qapp
        signal.signal(signal.SIGINT, quit_qapp)

    def _restore_sigint_handler(self) -> None:
        handler = self._sigint_handler
        if handler is None or threading.current_thread() is not threading.main_thread():
            return
        if signal.getsignal(signal.SIGINT) is handler:
            signal.signal(signal.SIGINT, self._previous_sigint_handler)
        self._sigint_handler = None
        self._previous_sigint_handler = None

    def _restore_qt_surface_format(self) -> None:
        owned = self._owned_qt_surface_format
        previous = self._previous_qt_surface_format
        if owned is None or previous is None:
            return
        if QtGui.QSurfaceFormat.defaultFormat() == owned:
            QtGui.QSurfaceFormat.setDefaultFormat(previous)
        self._owned_qt_surface_format = None
        self._previous_qt_surface_format = None

    def _window(self) -> VispyFrontendWindow:
        actor = self._actor()
        if not isinstance(actor, VispyFrontendWindow):
            raise TypeError(f"VispyActorHost expected VispyFrontendWindow, got {type(actor)!r}")
        return actor

    def _drain_inbound_messages(self, deadline_s: float) -> list[Message[MessagePayload]]:
        batch: list[Message[MessagePayload]] = []
        while self._inbound_messages and len(batch) < FRONTEND_MAX_INBOUND_MESSAGES_PER_STEP:
            if batch and time.monotonic() >= deadline_s:
                break
            batch.append(self._inbound_messages.popleft())
        if self._inbound_messages:
            perf_log(
                "frontend",
                "defer_inbound_messages",
                drained_count=len(batch),
                remaining_count=len(self._inbound_messages),
            )
        return batch

    def _flush_outbound(self, window: VispyFrontendWindow) -> int:
        if self.channel is None:
            return 0
        sent_count = 0
        for message in window.take_outbound_messages():
            self.channel.send(message)
            sent_count += 1
        return sent_count


__all__ = ["VispyActorHost"]
