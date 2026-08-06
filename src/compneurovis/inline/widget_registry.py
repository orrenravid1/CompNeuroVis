"""Public registry for optional named widget authoring."""

from __future__ import annotations

from collections.abc import Callable

from compneurovis.inline.widgets.api import Widget


WidgetFactory = Callable[..., Widget]
_widget_factories: dict[str, WidgetFactory] = {}
_reserved_widget_names: set[str] = set()


def register_widget(name: str, factory: WidgetFactory) -> None:
    """Expose a widget as a dynamic ``source.<name>(...)`` method.

    The factory builds a :class:`Widget` from the call arguments. The resulting
    method is the same ``source.add(factory(...))`` funnel on every source type.
    App-local scripts may register at import time; no separate distribution is
    required.
    """
    key = str(name).strip()
    if not key:
        raise ValueError("Widget name cannot be empty")
    if key.startswith("_"):
        raise ValueError("Widget name cannot start with '_'")

    if key in _reserved_widget_names:
        raise ValueError(
            f"source.{key}(...) is already a built-in source method; choose another name"
        )
    existing = _widget_factories.get(key)
    if existing is not None and existing is not factory:
        raise ValueError(f"source.{key}(...) is already registered")
    _widget_factories[key] = factory


def widget_factory(name: str) -> WidgetFactory | None:
    """Return the registered factory for one dynamic source name."""
    return _widget_factories.get(str(name))


def registered_widgets() -> tuple[str, ...]:
    """Return registered dynamic widget names in deterministic order."""
    return tuple(sorted(_widget_factories))


def widget_name_taken(name: str) -> bool:
    """Whether a first-party or dynamically registered widget owns a name."""
    key = str(name)
    return key in _reserved_widget_names or key in _widget_factories


def _reserve_widget_names(names) -> None:
    """Reserve statically declared source methods during facade definition."""
    for name in names:
        key = str(name)
        if key in _widget_factories:
            raise ValueError(
                f"source.{key}(...) was dynamically registered before the "
                "first-party source facade reserved that name"
            )
        _reserved_widget_names.add(key)


__all__ = [
    "WidgetFactory",
    "register_widget",
    "registered_widgets",
    "widget_factory",
    "widget_name_taken",
]
