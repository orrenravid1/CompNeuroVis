"""Small public contract used to author reusable source widgets."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any, Callable, Generic, TYPE_CHECKING, TypeVar

import numpy as np

from compneurovis.core.app_spec import PANEL_KIND_EXTENSION, PanelSpec
from compneurovis.core.geometry import ExtensionGeometrySpec
from compneurovis.core.operators import ExtensionOperatorSpec
from compneurovis.core.selections import SelectionSpec
from compneurovis.core.views import ExtensionViewSpec
from compneurovis.inline._ids import slug
from compneurovis.inline.compiler import SpecBinding, Binding
from compneurovis.inline.data_producers import (
    SeriesProducer,
    SeriesReaders,
    SnapshotProducer,
)
from compneurovis.inline.refs import (
    DataRef,
    GeometryRef,
    PanelRef,
    SelectionRef,
    bind,
)

if TYPE_CHECKING:
    from compneurovis.inline.sources import InlineSourceBase


RefT = TypeVar("RefT")
_MISSING = object()


class Widget(ABC, Generic[RefT]):
    """A reusable source-level declaration attached with ``source.add()``.

    Subclass and implement ``declare``; the abstract method makes a missing
    implementation a definition-time error rather than an attach-time one.
    """

    __slots__ = ()

    @abstractmethod
    def declare(self, context: WidgetAuthoringContext) -> RefT:
        """Declare this widget through the provided authoring context."""
        raise NotImplementedError


class WidgetAuthoringContext:
    """The complete API needed by a source-level widget author."""

    __slots__ = ("__namespace", "__source")

    def __init__(self, source: InlineSourceBase) -> None:
        self.__source = source
        self.__namespace = source._allocate_widget_namespace()

    def _local_id(self, value: str) -> str:
        return f"{self.__namespace}_{slug(value)}"

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
            field_id=f"{self._local_id(name)}_data",
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

    def series(
        self,
        name: str,
        *,
        read: SeriesReaders,
        x: Callable[[], float] | None = None,
        unit: str = "a.u.",
        max_samples: int = 2400,
    ) -> DataRef:
        """Declare append-semantics (streaming time-series) data for a widget.

        The streaming parallel of ``data``: each frame appends a sample, so a
        view can show a scrolling trace. ``read`` is a no-argument reader, or a
        mapping of label -> reader for multiple series over the same time axis.
        ``x`` supplies the time coordinate; ``None`` uses sample order.
        """
        producer = SeriesProducer(
            name=name,
            read=read,
            x=x if callable(x) else None,
            y_unit=unit,
            max_samples=max_samples,
        )
        self._add_series(producer)
        self.__source._add_widget(
            field_builders=(lambda backend, _p=producer: _p._field_spec(),)
        )
        return DataRef(
            _field_id=producer._field_id,
            _series_dim="series",
            _selectors={},
            _unit=unit,
        )

    def grid(
        self,
        name: str,
        *,
        values: Any = None,
        read: Callable[[], Any] | None = None,
        x: Any | None = None,
        y: Any | None = None,
        x_dim: str = "x",
        y_dim: str = "y",
        unit: str | None = None,
    ) -> DataRef:
        """Declare a 2-D field with coordinates — surface-class snapshot data.

        The 2-D parallel of ``data``: ``values`` is a 2-D array over ``(y, x)``;
        ``x`` / ``y`` give the coordinates (default integer indices). Static, or
        callable-backed via ``read``. This is the data shape ``surface`` uses,
        now authorable by any widget rather than a built-in privilege.
        """
        if values is None and read is None:
            raise ValueError("grid(...) requires values=... or read=...")
        raw = read() if read is not None else values
        array = np.asarray(raw, dtype=np.float32)
        if array.ndim != 2:
            raise ValueError(f"grid({name!r}) values must be 2-D")
        y_count, x_count = array.shape
        x_coords = (
            np.arange(x_count, dtype=np.float32)
            if x is None
            else np.asarray(x, dtype=np.float32)
        )
        y_coords = (
            np.arange(y_count, dtype=np.float32)
            if y is None
            else np.asarray(y, dtype=np.float32)
        )
        producer = self.__source._declare_grid_field(
            field_id=f"{self._local_id(name)}_grid",
            dims=(y_dim, x_dim),
            coords={y_dim: y_coords, x_dim: x_coords},
            values=values,
            read=read,
            unit=unit,
            replace_includes_coords=True,
        )
        self.__source._add_widget(
            field_builders=(lambda backend, _p=producer: _p.field_spec(),)
        )
        return DataRef(
            _field_id=producer.field_id,
            _series_dim=None,
            _selectors={},
            _unit=unit,
        )

    def view(
        self,
        kind: str,
        name: str,
        *,
        inputs: Mapping[str, DataRef] | None = None,
        geometries: Mapping[str, GeometryRef] | None = None,
        selections: Mapping[str, SelectionRef] | None = None,
        properties: Mapping[str, Any] | None = None,
        title: Any = None,
        panel_id: str | None = None,
        panel_kind: str = PANEL_KIND_EXTENSION,
        max_refresh_hz: float | None = None,
    ) -> PanelRef:
        """Declare one view without exposing AppSpec internals.

        ``panel_kind`` is the frontend panel category, defaulting to an extension
        panel. A widget whose renderer draws a first-class surface may declare a
        native kind such as ``PANEL_KIND_VIEW_3D``. Frontends decide which host
        families they implement; Vispy supports extension, view_3d, and controls.
        """
        name_slug = self._local_id(name)
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
                        geometries={
                            str(role): geometry.id
                            for role, geometry in (geometries or {}).items()
                        },
                        selections={
                            str(role): selection.id
                            for role, selection in (selections or {}).items()
                        },
                        properties=_bind_tree(properties or {}),
                        max_refresh_hz=max_refresh_hz,
                        panel_kind=panel_kind,
                    ),
                ),
                panel=PanelSpec(
                    id=resolved_panel_id,
                    kind=panel_kind,
                    view_ids=(view_id,),
                ),
            )
        )
        return PanelRef(resolved_panel_id)

    def geometry(
        self,
        kind: str,
        name: str,
        *,
        data: Mapping[str, Any],
        metadata: Mapping[str, Any] | None = None,
    ) -> GeometryRef:
        """Declare immutable geometry without exposing an AppSpec constructor."""
        geometry_id = f"{self._local_id(name)}_{slug(kind)}_geometry"
        spec = ExtensionGeometrySpec(
            id=geometry_id,
            kind=kind,
            data=data,
            metadata={} if metadata is None else metadata,
        )
        self._add_binding(SpecBinding(geometries=(spec,)))
        return GeometryRef(id=geometry_id, kind=spec.kind)

    def selection(
        self,
        name: str,
        *,
        geometry: GeometryRef,
        initial: Any = None,
        multiple: bool = False,
    ) -> SelectionRef:
        """Declare fragment-scoped selection state for a geometry."""
        selection_id = f"{self._local_id(name)}_selection"
        if initial is None:
            initial_ids: tuple[str, ...] = ()
        elif multiple:
            if isinstance(initial, (str, bytes)):
                raise ValueError(
                    "selection(..., multiple=True) expects an iterable of entity ids"
                )
            initial_ids = tuple(str(entity_id) for entity_id in initial)
        else:
            if isinstance(initial, (list, tuple, set, np.ndarray)):
                values = tuple(initial)
                if values:
                    raise ValueError(
                        "single selection initial value must be one entity id"
                    )
                initial_ids = ()
            else:
                initial_ids = (str(initial),)
        self._add_binding(
            SpecBinding(
                selections=(
                    SelectionSpec(
                        id=selection_id,
                        geometry_id=geometry.id,
                        initial=initial_ids,
                        multiple=multiple,
                    ),
                )
            )
        )
        return SelectionRef(selection_id, multiple=multiple)

    def operator(
        self,
        kind: str,
        name: str,
        *,
        inputs: Mapping[str, DataRef],
        geometries: Mapping[str, GeometryRef] | None = None,
        properties: Mapping[str, Any] | None = None,
        contributes_to: Sequence[PanelRef] = (),
    ) -> DataRef:
        """Declare a data-producing operator and optional panel contributions."""
        operator_id = f"{self._local_id(name)}_{slug(kind)}_operator"
        spec = ExtensionOperatorSpec(
            id=operator_id,
            kind=kind,
            inputs={str(role): data._field_id for role, data in inputs.items()},
            geometries={
                str(role): geometry.id for role, geometry in (geometries or {}).items()
            },
            properties=_bind_tree(properties or {}),
        )
        panel_operator_ids = {panel.id: (operator_id,) for panel in contributes_to}
        self._add_binding(
            SpecBinding(
                operators=(spec,),
                panel_operator_ids=panel_operator_ids,
            )
        )
        return DataRef(_field_id=operator_id)

    def _add_binding(self, binding: Binding) -> None:
        self.__source._add_widget_binding(binding)

    def _add_series(self, binding: SeriesProducer) -> None:
        self.__source._add_series(binding)

    def _declare_field(self, **kwargs: Any) -> SnapshotProducer:
        return self.__source._declare_field(**kwargs)

    def _declare_grid_field(self, **kwargs: Any) -> SnapshotProducer:
        return self.__source._declare_grid_field(**kwargs)

    def _register_surface(self, binding: Any) -> None:
        self.__source._add_surface(binding)

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
