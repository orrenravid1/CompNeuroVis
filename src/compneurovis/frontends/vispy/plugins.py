"""Deferred discovery for Vispy frontend contributions.

An app-local widget can register an import string without importing Qt/Vispy in
the authoring or backend process. The frontend resolves the string only when it
is ready to build the UI. Installed distributions use the same callback
contract through the compneurovis.vispy_plugins entry-point group.
"""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import entry_points

PLUGIN_ENTRY_POINT_GROUP = "compneurovis.vispy_plugins"

_local_plugins: dict[str, None] = {}
_loaded_local_plugins: set[str] = set()
_loading_local_plugins: set[str] = set()
_loaded_entry_points: set[tuple[str, str, str]] = set()


def register_vispy_plugin(import_path: str) -> None:
    """Defer one app-local Vispy registration callback.

    The import path is "module:callable"; omitting the callable uses "register".
    Calling this function is safe in an app script: it stores only the string and
    does not import the renderer module.
    """
    normalized = str(import_path).strip()
    module_name, separator, attribute = normalized.partition(":")
    if not module_name or (separator and not attribute) or ":" in attribute:
        raise ValueError(
            "Vispy plugin import path must be 'module:callable' "
            "(or just 'module' for module:register)"
        )
    _local_plugins.setdefault(normalized, None)


def _load_local_plugin(import_path: str) -> None:
    if import_path in _loaded_local_plugins or import_path in _loading_local_plugins:
        return
    module_name, _, attribute = import_path.partition(":")
    callback_name = attribute or "register"
    _loading_local_plugins.add(import_path)
    try:
        module = import_module(module_name)
        callback = getattr(module, callback_name, None)
        if not callable(callback):
            raise TypeError(
                f"Vispy plugin {import_path!r} must resolve to a callable"
            )
        callback()
    except Exception:
        _loading_local_plugins.discard(import_path)
        raise
    _loading_local_plugins.discard(import_path)
    _loaded_local_plugins.add(import_path)


def load_vispy_plugins() -> None:
    """Load pending local and installed contributions in the frontend process."""
    while True:
        pending = [
            path for path in _local_plugins if path not in _loaded_local_plugins
        ]
        if not pending:
            break
        for import_path in pending:
            _load_local_plugin(import_path)

    discovered = entry_points()
    selected = (
        discovered.select(group=PLUGIN_ENTRY_POINT_GROUP)
        if hasattr(discovered, "select")
        else discovered.get(PLUGIN_ENTRY_POINT_GROUP, ())
    )
    for entry_point in selected:
        identity = (
            entry_point.group,
            entry_point.name,
            entry_point.value,
        )
        if identity in _loaded_entry_points:
            continue
        callback = entry_point.load()
        if not callable(callback):
            raise TypeError(
                f"Vispy plugin entry point {entry_point.name!r} must be callable"
            )
        callback()
        _loaded_entry_points.add(identity)

    for import_path in tuple(_local_plugins):
        _load_local_plugin(import_path)


__all__ = [
    "PLUGIN_ENTRY_POINT_GROUP",
    "load_vispy_plugins",
    "register_vispy_plugin",
]
