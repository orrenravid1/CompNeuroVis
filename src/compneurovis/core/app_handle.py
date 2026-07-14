from __future__ import annotations

import time
from typing import Any


class AppHandle:
    """Handle for an orchestrated app run."""

    def __init__(
        self,
        *,
        runtime: "AppRuntime",  # type: ignore[name-defined]
        items: list,
        results: dict,
        channels: dict | None = None,
        actors: list | None = None,
        bus_thread: "Any | None" = None,
    ) -> None:
        self._runtime = runtime
        self.items = items
        self.results = results
        self.channels: dict = channels or {}
        self.actors: list = actors or []
        self._bus_thread = bus_thread
        self._stopping = False
        self._stopped = False

    @property
    def runtime(self) -> "AppRuntime":  # type: ignore[name-defined]
        return self._runtime

    def widget(self, actor_id: str = "frontend") -> Any:
        """Return the widget produced by the named actor's run()."""
        return self.results.get(actor_id)

    def wait(self) -> None:
        fg = [(spec, host) for spec, host in self.items if spec.runs_in_foreground]
        if fg:
            _, fg_host = fg[0]
            try:
                fg_host.run()
            finally:
                self.stop()
            return

        processes = [
            p
            for p in (getattr(host, "_process", None) for _, host in self.items)
            if p is not None
        ]
        try:
            while not self._runtime.is_stopped():
                if processes and not any(p.is_alive() for p in processes):
                    break
                time.sleep(0.05)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self) -> None:
        if self._stopped or self._stopping:
            return
        self._stopping = True
        try:
            self._runtime.stop()
            for _, host in reversed(self.items):
                host.stop()
            if self._bus_thread is not None:
                self._bus_thread.stop()
            self._stopped = True
        finally:
            self._stopping = False


__all__ = ["AppHandle"]
