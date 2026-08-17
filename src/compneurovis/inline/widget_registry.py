"""Public registry shared by built-in and third-party widget authoring."""

from __future__ import annotations

from collections.abc import Callable

from compneurovis.inline._ids import authoring_method_name
from compneurovis.inline.widgets.api import Widget


WidgetFactory = Callable[..., Widget]
_widget_factories: dict[str, WidgetFactory] = {}
_reserved_widget_names: set[str] = set()
_first_party_widget_names: set[str] = set()


def register_widget(name: str, factory: WidgetFactory) -> None:
    """Expose a widget as a dynamic ``source.<name>(...)`` method.

    The factory builds a :class:`Widget` from the call arguments. The resulting
    method is the same ``source.add(factory(...))`` funnel on every source type.
    App-local scripts may register at import time; no separate distribution is
    required.
    """
    key = authoring_method_name(name, label="Widget name")
    if not callable(factory):
        raise TypeError("Widget factory must be callable")

    existing = _widget_factories.get(key)
    if existing is factory:
        return

    if key in _reserved_widget_names:
        raise ValueError(
            f"source.{key}(...) is already a built-in source method; choose another name"
        )
    from compneurovis.inline.control_registry import registered_controls

    if key in registered_controls():
        raise ValueError(
            f"source.{key}(...) is already a control or action authoring name"
        )
    if existing is not None:
        raise ValueError(f"source.{key}(...) is already registered")
    _widget_factories[key] = factory


def _register_first_party_widget(name: str, factory: WidgetFactory) -> None:
    """Install a built-in through the same registry exposed to app authors.

    This remains private because first-party ownership is a composition-root
    concern, not an escape hatch for bypassing public collision checks.
    """
    key = authoring_method_name(name, label="First-party widget name")
    if not callable(factory):
        raise TypeError("Widget factory must be callable")
    existing = _widget_factories.get(key)
    if existing is not None and existing is not factory:
        raise ValueError(f"source.{key}(...) is already registered")
    _widget_factories[key] = factory
    _first_party_widget_names.add(key)


def widget_factory(name: str) -> WidgetFactory | None:
    """Return the registered factory for one source authoring name."""
    return _widget_factories.get(str(name))


def registered_widgets() -> tuple[str, ...]:
    """Return every registered widget name in deterministic order."""
    return tuple(sorted(_widget_factories))


def widget_name_taken(name: str) -> bool:
    """Whether a first-party or dynamically registered widget owns a name."""
    key = str(name)
    return key in _reserved_widget_names or key in _widget_factories


def _reserve_widget_names(names) -> None:
    """Reserve statically declared source methods during facade definition."""
    from compneurovis.inline.control_registry import registered_controls

    shared_names = set(registered_controls())
    for name in names:
        key = str(name)
        if key in _widget_factories and key not in _first_party_widget_names:
            raise ValueError(
                f"source.{key}(...) was dynamically registered before the "
                "first-party source facade reserved that name"
            )
        if key not in _widget_factories and key not in shared_names:
            _reserved_widget_names.add(key)


__all__ = [
    "WidgetFactory",
    "register_widget",
    "registered_widgets",
    "widget_factory",
    "widget_name_taken",
]
