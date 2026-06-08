from __future__ import annotations

import threading

from compneurovis.core.app_spec import AppSpec
from compneurovis.core.diagnostics import DiagnosticsSpec


class AppRuntime:
    """Coordinator for a single app run.

    Holds the optional startup declaration (AppSpec) and the stop signal. The
    foreground/background launch lifecycle is the single implementation in
    AppHandle.wait(). Does not own simulation state, renderer state, channels,
    or actor construction logic.
    """

    def __init__(
        self,
        *,
        app_spec: AppSpec | None,
        diagnostics: DiagnosticsSpec | None = None,
    ) -> None:
        self._app_spec = app_spec
        self._diagnostics = diagnostics
        self._stop_event = threading.Event()

    @property
    def app_spec(self) -> AppSpec | None:
        """The optional startup AppSpec declaration — read-only after construction.

        May be None: in source-launched desktop runs, the script worker builds
        the model once and declares the AppSpec over the runtime channel. Actors
        must not mutate this object. Each actor that needs live app data derives
        an actor-local projection by deep-copying the seed and folding updates
        into that projection.
        """
        return self._app_spec

    @property
    def diagnostics(self) -> DiagnosticsSpec | None:
        return self._diagnostics

    def stop(self) -> None:
        self._stop_event.set()

    def is_stopped(self) -> bool:
        return self._stop_event.is_set()


__all__ = ["AppRuntime"]
