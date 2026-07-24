"""Small public contract used to author reusable source widgets."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Callable, Generic, Protocol, TYPE_CHECKING, TypeVar

import numpy as np

from compneurovis.core.app_spec import PANEL_KIND_EXTENSION, PanelSpec
from compneurovis.core.views import ExtensionViewSpec
from compneurovis.inline._ids import slug
from compneurovis.inline.compiler import SpecBinding, WidgetBinding
from compneurovis.inline.data_producers import SnapshotProducer
from compneurovis.inline.refs import DataRef, PanelRef, bind

if TYPE_CHECKING:
    from compneurovis.inline.sources import InlineSourceBase
    from compneurovis.inline.data_producers import SeriesProducer


RefT = TypeVar("RefT")
_MISSING = object()


class Widget(Protocol, Generic[RefT]):
    """A reusable source-level declaration attachable with ``source.add()``."""

    def attach(self, context: WidgetAuthoringContext) -> RefT:
        """Declare this widget through the provided authoring context."""


class WidgetAuthoringContext:
    """The complete API needed by a source-level widget author."""

    __slots__ = ("__source",)

    def __init__(self, source: InlineSourceBase) -> None:
        self.__source = source

    def add(self, widget: Widget[RefT]) -> RefT:
        attach = getattr(widget, "attach", None)
        if not callable(attach):
            raise TypeError(
                f"source.add() expects an object with attach(context), got {type(widget).__name__}"
            )
        return attach(self)

    def data(
        self,
        name: str,
        *,
        values: Any = _MISSING,
        read: Callable[[], Any] | None = None,
        source: DataRef | None = None,
        labels: Sequence[str] | None = None,
        unit: str | None = None,
    ) -> DataRef:
        """Declare or reuse data consumed by a widget."""
        if source is not None:
            if values is not _MISSING or read is not None:
                raise ValueError(
                    "data(...) accepts source=..., or values=/read=..., not both"
                )
            return source
        if values is not _MISSING and read is not None:
            raise ValueError("data(...) accepts values=... or read=..., not both")
        if values is _MISSING and read is None:
            raise ValueError("data(...) requires values=..., read=..., or source=...")
        if values is _MISSING:
            if labels is None:
                raise ValueError("data(..., read=...) requires labels=(...)")
            initial_values: Any = np.zeros(len(labels), dtype=np.float32)
        else:
            initial_values = values
        resolved_labels = (
            tuple(str(label) for label in labels)
            if labels is not None
            else tuple(
                str(index)
                for index in range(np.asarray(initial_values).reshape(-1).size)
            )
        )
        binding = self._declare_field(
            field_id=f"{slug(name)}_data",
            dim="item",
            labels=resolved_labels,
            values=initial_values,
            read=read,
            unit=unit,
        )
        self.__source._add_widget(
            field_builders=(lambda backend, _binding=binding: _binding.field_spec(),)
        )
        return DataRef(
            _field_id=binding.field_id,
            _series_dim="item",
            _selectors={},
            _unit=unit,
        )

    def view(
        self,
        kind: str,
        name: str,
        *,
        inputs: Mapping[str, DataRef] | None = None,
        properties: Mapping[str, Any] | None = None,
        title: Any = None,
        panel_id: str | None = None,
        max_refresh_hz: float | None = None,
    ) -> PanelRef:
        """Declare one extension view without exposing AppSpec internals."""
        name_slug = slug(name)
        view_id = f"{name_slug}_{slug(kind)}"
        resolved_panel_id = panel_id or f"{name_slug}-panel"
        self._add_binding(
            SpecBinding(
                views=(
                    ExtensionViewSpec(
                        id=view_id,
                        title=bind(name if title is None else title),
                        kind=kind,
                        inputs={
                            str(role): data._field_id
                            for role, data in (inputs or {}).items()
                        },
                        properties=_bind_tree(properties or {}),
                        max_refresh_hz=max_refresh_hz,
                    ),
                ),
                panel=PanelSpec(
                    id=resolved_panel_id,
                    kind=PANEL_KIND_EXTENSION,
                    view_ids=(view_id,),
                ),
            )
        )
        return PanelRef(resolved_panel_id)

    def line(self, name: str, **kwargs: Any):
        """Compose a line widget inside another widget."""
        return self.__source.line(name, **kwargs)

    def bar(self, name: str, **kwargs: Any):
        """Compose a bar widget inside another widget."""
        return self.__source.bar(name, **kwargs)

    def _add_binding(self, binding: WidgetBinding) -> None:
        self.__source._add_widget_binding(binding)

    def _add_trace(self, binding: SeriesProducer) -> None:
        self.__source._add_trace(binding)

    def _declare_field(self, **kwargs: Any) -> SnapshotProducer:
        return self.__source._declare_field(**kwargs)

    def _register_surface(self, binding: Any) -> None:
        self.__source._add_surface(binding)

    def _register_grid_slice(self, binding: Any) -> None:
        self.__source._add_grid_slice(binding)

    def _register_geometry(
        self,
        geometry: Any,
        *,
        field_builders: Sequence[Any] = (),
    ) -> None:
        self.__source._geometries.append(geometry)
        self.__source._add_widget(
            geometries=(geometry,),
            field_builders=field_builders,
        )

    def _register_morphology(self, binding: Any, *, panel: bool) -> None:
        if panel:
            self._add_binding(binding)

    def _set_selection_mode(self, key: str, select_multiple: bool) -> None:
        self.__source._selection_modes[key] = select_multiple

    def _set_initial_value(self, key: str, value: Any) -> None:
        self.__source._initial_values.append((key, value))


def _bind_tree(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _bind_tree(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_bind_tree(item) for item in value)
    if isinstance(value, list):
        return [_bind_tree(item) for item in value]
    return bind(value)


__all__ = ["Widget", "WidgetAuthoringContext"]
