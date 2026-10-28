from __future__ import annotations

import time
from typing import Any, TYPE_CHECKING

from compneurovis.core.diagnostics import release_diagnostics

if TYPE_CHECKING:
    from compneurovis.core.runtime.app import AppRuntime


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
        transport_fabric: "Any | None" = None,
        diagnostics_token: object | None = None,
    ) -> None:
        self._runtime = runtime
        self.items = items
        self.results = results
        self.channels: dict = channels or {}
        self.actors: list = actors or []
        self._bus_thread = bus_thread
        self._transport_fabric = transport_fabric
        self._diagnostics_token = diagnostics_token
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
            failed_processes = []
            try:
                fg_host.run()
            finally:
                failed_processes = self._failed_processes()
                self.stop()
            self._raise_bus_failure()
            self._raise_process_failures(failed_processes)
            return

        processes = [
            p
            for p in (getattr(host, "_process", None) for _, host in self.items)
            if p is not None
        ]
        failed_processes = []
        try:
            while not self._runtime.is_stopped():
                failed_processes = self._failed_processes()
                if failed_processes:
                    break
                if processes and not any(p.is_alive() for p in processes):
                    break
                time.sleep(0.05)
        except KeyboardInterrupt:
            pass
        finally:
            if not failed_processes:
                failed_processes = self._failed_processes()
            self.stop()
        self._raise_bus_failure()
        self._raise_process_failures(failed_processes)

    def _raise_bus_failure(self) -> None:
        if self._bus_thread is not None:
            self._bus_thread.raise_if_failed()

    def _failed_processes(self) -> list[tuple[str, int]]:
        failures: list[tuple[str, int]] = []
        for spec, host in self.items:
            process = getattr(host, "_process", None)
            exitcode = None if process is None else process.exitcode
            if exitcode not in (None, 0):
                failures.append((spec.id, exitcode))
        return failures

    @staticmethod
    def _raise_process_failures(failures: list[tuple[str, int]]) -> None:
        if not failures:
            return
        details = ", ".join(
            f"{actor_id!r} (exit code {exitcode})"
            for actor_id, exitcode in failures
        )
        raise RuntimeError(f"Actor subprocess failed: {details}")

    def stop(self) -> None:
        if self._stopped or self._stopping:
            return
        self._stopping = True
        errors: list[Exception] = []
        try:
            try:
                self._runtime.stop()
            except Exception as exc:
                errors.append(exc)
            # Stop transport polling before hosts close their peer endpoints.
            # Otherwise an ordinary shutdown can race with the bus and be
            # misreported as a transport failure.
            if self._bus_thread is not None:
                try:
                    self._bus_thread.stop()
                except Exception as exc:
                    errors.append(exc)
            for _, host in reversed(self.items):
                try:
                    host.stop()
                except Exception as exc:
                    errors.append(exc)
            if self._transport_fabric is not None:
                try:
                    self._transport_fabric.close()
                except Exception as exc:
                    errors.append(exc)
            if self._diagnostics_token is not None:
                token = self._diagnostics_token
                self._diagnostics_token = None
                try:
                    release_diagnostics(token)
                except Exception as exc:
                    errors.append(exc)
        finally:
            self._stopped = True
            self._stopping = False
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise ExceptionGroup("CompNeuroVis app cleanup failed", errors)


__all__ = ["AppHandle"]
