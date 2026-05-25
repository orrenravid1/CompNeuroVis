from __future__ import annotations

import signal
import sys
import time

from PyQt6 import QtCore, QtWidgets
from vispy import app as vispy_app

from compneurovis.core.actor import ActorSource
from compneurovis.core.channel import Channel
from compneurovis.core.hosts import ActorHost
from compneurovis.core.messages import StopActor
from compneurovis.core.runtime import AppRuntime
from compneurovis.frontends.vispy.frontend import VispyFrontendWindow

# Qt's event loop must run in the main process and main thread: a VisPy/Qt
# constraint, not a generic architectural one. Non-Qt actors can use the
# ordinary ActorProcess path.


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

    def start(self) -> None:
        if QtWidgets.QApplication.instance() is None:
            self._qapp = QtWidgets.QApplication(sys.argv)
        else:
            self._qapp = QtWidgets.QApplication.instance()
        signal.signal(signal.SIGINT, lambda *_: self._qapp.quit())
        window = super().start(self._actor_source, self._runtime.app_spec)
        assert isinstance(window, VispyFrontendWindow)
        self.timer = QtCore.QTimer(window)
        self.timer.timeout.connect(self.step)
        self.timer.start(1000 // 60)
        window.show()

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
        if self.channel is not None:
            for message in self.channel.poll():
                if isinstance(message.payload, StopActor):
                    self._stop_requested = True
                    self._runtime.stop()
                    if self._qapp is not None:
                        self._qapp.quit()
                    return
                window._handle_update_messages([message], poll_started=started, timer_gap_ms=timer_gap_ms)
            for message in window.take_outbound_messages():
                self.channel.send(message)
        window.flush_due_refreshes(now=started)

    def stop(self) -> None:
        if self.timer is not None:
            self.timer.stop()
        super().stop()

    def _window(self) -> VispyFrontendWindow:
        actor = self._actor()
        if not isinstance(actor, VispyFrontendWindow):
            raise TypeError(f"VispyActorHost expected VispyFrontendWindow, got {type(actor)!r}")
        return actor


__all__ = ["VispyActorHost"]
