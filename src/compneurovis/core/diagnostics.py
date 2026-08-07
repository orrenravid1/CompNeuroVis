from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from compneurovis.core.specs import SpecBase


@dataclass(frozen=True, slots=True)
class DiagnosticsSpec(SpecBase):
    perf_log_enabled: bool = False
    perf_log_dir: str | Path | None = None
    perf_echo_stderr: bool = False


def configure_diagnostics(diagnostics: DiagnosticsSpec | None) -> None:
    from compneurovis.core.runtime.performance import clear_perf_logging_configuration, configure_perf_logging

    if diagnostics is None:
        clear_perf_logging_configuration()
    else:
        configure_perf_logging(diagnostics)


def acquire_diagnostics(diagnostics: DiagnosticsSpec | None) -> object:
    """Acquire app-lifetime ownership of the process diagnostics settings."""

    from compneurovis.core.runtime.performance import (
        acquire_perf_logging_configuration,
    )

    return acquire_perf_logging_configuration(diagnostics)


def release_diagnostics(token: object) -> None:
    """Release a diagnostics lease. Safe to call more than once."""

    from compneurovis.core.runtime.performance import (
        release_perf_logging_configuration,
    )

    release_perf_logging_configuration(token)


__all__ = [
    "DiagnosticsSpec",
    "acquire_diagnostics",
    "configure_diagnostics",
    "release_diagnostics",
]
