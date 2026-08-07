from __future__ import annotations

from datetime import datetime
from dataclasses import dataclass
import json
import multiprocessing as mp
import os
from pathlib import Path
import sys
from threading import Lock
import time
from typing import Any

from compneurovis.core.diagnostics import DiagnosticsSpec

_WRITE_LOCK = Lock()
_CONFIG_LOCK = Lock()
_TRUE_VALUES = {"1", "true", "yes", "on"}
_CONFIG_UNSET = object()
_configured_state: "_PerfLoggingState | object" = _CONFIG_UNSET
_configuration_leases: list[tuple[object, "_PerfLoggingState"]] = []


@dataclass(frozen=True, slots=True)
class _PerfLoggingState:
    log_path: Path | None = None
    echo_stderr: bool = False


def perf_logging_enabled() -> bool:
    state = _active_state()
    return state.log_path is not None or state.echo_stderr


def configure_perf_logging(diagnostics: DiagnosticsSpec) -> None:
    global _configured_state
    state = _resolve_diagnostics_state(diagnostics)
    with _CONFIG_LOCK:
        _configured_state = state


def clear_perf_logging_configuration() -> None:
    global _configured_state
    with _CONFIG_LOCK:
        _configured_state = _CONFIG_UNSET


def acquire_perf_logging_configuration(
    diagnostics: DiagnosticsSpec | None,
) -> object:
    """Temporarily own the process logging configuration for one app run.

    Leases form a stack so an app restores the configuration that preceded it
    when it stops. Releasing an older, overlapping lease is also safe: the most
    recently acquired live lease remains authoritative.
    """

    state = (
        _resolve_env_state()
        if diagnostics is None
        else _resolve_diagnostics_state(diagnostics)
    )
    token = object()
    with _CONFIG_LOCK:
        _configuration_leases.append((token, state))
    return token


def release_perf_logging_configuration(token: object) -> None:
    """Release an app-owned logging configuration; repeated release is a no-op."""

    with _CONFIG_LOCK:
        for index, (candidate, _) in enumerate(_configuration_leases):
            if candidate is token:
                del _configuration_leases[index]
                break


def perf_log(component: str, event: str, **fields: Any) -> None:
    state = _active_state()
    path = _log_path(state)
    if path is None and not state.echo_stderr:
        return

    record = {
        "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
        "mono_s": round(time.monotonic(), 6),
        "pid": os.getpid(),
        "process": mp.current_process().name,
        "component": component,
        "event": event,
    }
    for key, value in fields.items():
        record[key] = _to_jsonable(value)

    line = json.dumps(record, separators=(",", ":"), sort_keys=False)

    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with _WRITE_LOCK:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.write("\n")

    if state.echo_stderr:
        sys.stderr.write(line + "\n")
        sys.stderr.flush()


def _to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _to_jsonable(inner) for key, inner in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(inner) for inner in value]
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:
            pass
    shape = getattr(value, "shape", None)
    if shape is not None:
        return {"shape": list(shape)}
    return str(value)


def _active_state() -> _PerfLoggingState:
    with _CONFIG_LOCK:
        if _configuration_leases:
            return _configuration_leases[-1][1]
        state = _configured_state
    if state is not _CONFIG_UNSET:
        return state
    return _resolve_env_state()


def _resolve_diagnostics_state(diagnostics: DiagnosticsSpec) -> _PerfLoggingState:
    enabled = bool(
        diagnostics.perf_log_enabled
        or diagnostics.perf_log_dir is not None
        or diagnostics.perf_echo_stderr
    )
    if not enabled:
        return _PerfLoggingState()
    log_path = Path(diagnostics.perf_log_dir) if diagnostics.perf_log_dir is not None else _default_log_dir()
    return _PerfLoggingState(log_path=log_path, echo_stderr=bool(diagnostics.perf_echo_stderr))


def _resolve_env_state() -> _PerfLoggingState:
    raw = os.getenv("COMPNV_PERF_LOG", "").strip()
    if not raw:
        return _PerfLoggingState(
            log_path=None,
            echo_stderr=os.getenv("COMPNV_PERF_STDERR", "").strip().lower() in _TRUE_VALUES,
        )

    if raw.lower() in _TRUE_VALUES:
        log_path = _default_log_dir()
    else:
        log_path = Path(raw)
    return _PerfLoggingState(
        log_path=log_path,
        echo_stderr=os.getenv("COMPNV_PERF_STDERR", "").strip().lower() in _TRUE_VALUES,
    )


def _log_path(state: _PerfLoggingState) -> Path | None:
    if state.log_path is None:
        return None
    process_name = _slug(mp.current_process().name)
    pid = os.getpid()
    if state.log_path.suffix:
        suffix = state.log_path.suffix or ".jsonl"
        return state.log_path.with_name(f"{state.log_path.stem}-{process_name}-{pid}{suffix}")
    return state.log_path / f"compneurovis-perf-{process_name}-{pid}.jsonl"


def _default_log_dir() -> Path:
    return Path.cwd() / ".compneurovis" / "perf-logs"


def _slug(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-") or "process"
