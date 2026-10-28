"""Small public contract used to author reusable source widgets."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any, Callable, Generic, TYPE_CHECKING, TypeVar

import numpy as np

from compneurovis.core.app_spec import PANEL_KIND_STANDALONE, PanelSpec
from compneurovis.core.geometry import GeometrySpec
from compneurovis.core.clicks import ClickSpec
from compneurovis.core.pointer_interactions import PointerInteractionSpec
from compneurovis.core.pointer import HitTargetSpec
from compneurovis.core.field import FieldRetentionSpec
from compneurovis.core.operators import OperatorSpec
from compneurovis.core.selections import SelectionSpec
from compneurovis.core.views import ViewSpec
from compneurovis.core.visual_contributions import VisualContributionSpec
from compneurovis.inline._ids import slug
from compneurovis.inline.compiler import SpecBinding, Binding
from compneurovis.inline.data_producers import (
    SeriesProducer,
    SeriesReaders,
    SnapshotProducer,
)
from compneurovis.inline.refs import (
    DataRef,
    ClickRef,
    EntityClickRef,
    EntityPointerRef,
    GeometryRef,
    HitTargetRef,
    PanelRef,
    PointerInteractionRef,
    SelectionRef,
    bind,
)
from compneurovis.inline.interactions import (
    ClickHandler,
    ClickHandlerBinding,
    EntityClickHandler,
    PointerInteractionHandler,
    PointerInteractionHandlerBinding,
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
        dim: str = "item",
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
            dim=dim,
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
            _series_dim=dim,
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

    def snapshot(
        self,
        name: str,
        *,
        dims: Sequence[str],
        coords: Mapping[str, Any],
        values: Any = _MISSING,
        read: Callable[[], Any] | None = None,
        unit: str | None = None,
    ) -> DataRef:
        """Declare an N-dimensional snapshot with explicit coordinates.

        This is the shape-neutral counterpart of ``data`` and ``grid``. Its
        dimension names are stable, while coordinate values and lengths may be
        replaced atomically through ``ctx.set_data(..., coords=...)``. Mutable
        collections therefore remain ordinary fields instead of becoming a
        privileged core concept.
        """
        if values is not _MISSING and read is not None:
            raise ValueError("snapshot(...) accepts values=... or read=..., not both")
        if values is _MISSING and read is None:
            raise ValueError("snapshot(...) requires values=... or read=...")
        resolved_dims = tuple(str(dim).strip() for dim in dims)
        if not resolved_dims or any(not dim for dim in resolved_dims):
            raise ValueError("snapshot(...) dims must be non-empty strings")
        if len(set(resolved_dims)) != len(resolved_dims):
            raise ValueError("snapshot(...) dims cannot contain duplicates")
        if set(coords) != set(resolved_dims):
            raise ValueError("snapshot(...) coords keys must exactly match dims")
        producer = self.__source._declare_grid_field(
            field_id=f"{self._local_id(name)}_snapshot",
            dims=resolved_dims,
            coords={dim: coords[dim] for dim in resolved_dims},
            values=None if values is _MISSING else values,
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
        hit_targets: Mapping[str, HitTargetRef] | None = None,
        selections: Mapping[str, SelectionRef] | None = None,
        clicks: Mapping[str, ClickRef] | None = None,
        properties: Mapping[str, Any] | None = None,
        title: Any = None,
        panel_id: str | None = None,
        panel_kind: str = PANEL_KIND_STANDALONE,
        max_refresh_hz: float | None = None,
    ) -> PanelRef:
        """Declare one view without exposing AppSpec internals.

        ``panel_kind`` is the frontend panel category, defaulting to a standalone
        panel. A widget whose renderer draws a first-class surface may declare a
        capable host kind such as ``"scene_3d"``. Frontends decide which
        host registrations they implement; Vispy ships standalone, scene_3d, and
        controls registrations.
        """
        name_slug = self._local_id(name)
        view_id = f"{name_slug}_{slug(kind)}"
        resolved_panel_id = panel_id or f"{name_slug}-panel"
        resolved_hit_targets = {
            str(role): target.id for role, target in (hit_targets or {}).items()
        }
        for role, interaction in (clicks or {}).items():
            normalized_role = str(role)
            current = resolved_hit_targets.get(normalized_role)
            if current is not None and current != interaction.hit_target_id:
                raise ValueError(
                    f"View hit role {normalized_role!r} maps to conflicting hit targets"
                )
            resolved_hit_targets[normalized_role] = interaction.hit_target_id
        self._add_binding(
            SpecBinding(
                views=(
                    ViewSpec(
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
                        hit_targets=resolved_hit_targets,
                        clicks={
                            str(role): interaction.id
                            for role, interaction in (clicks or {}).items()
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

    def require_retention(
        self,
        source: DataRef,
        *,
        append_dim: str,
        min_duration: float | None = None,
        min_samples: int | None = None,
    ) -> None:
        """Declare history needed from a producer without naming its consumer."""
        requirement = FieldRetentionSpec(
            append_dim=append_dim,
            min_duration=min_duration,
            min_samples=min_samples,
        )
        self._add_binding(
            SpecBinding(
                field_retention={source._field_id: (requirement,)},
            )
        )

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
        spec = GeometrySpec(
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
        geometry: GeometryRef | None = None,
        hit_target: HitTargetRef | None = None,
        item_kind: str | None = None,
        initial: Any = None,
        multiple: bool = False,
    ) -> SelectionRef:
        """Declare typed selection state over a geometry or exact hit target."""
        if (geometry is None) == (hit_target is None):
            raise ValueError(
                "selection(...) requires exactly one of geometry= or hit_target="
            )
        if geometry is not None and not isinstance(geometry, GeometryRef):
            raise TypeError("selection(...) geometry must be a GeometryRef")
        if hit_target is not None and not isinstance(hit_target, HitTargetRef):
            raise TypeError("selection(...) hit_target must be a HitTargetRef")
        target_type = "geometry" if geometry is not None else "hit_target"
        target_id = geometry.id if geometry is not None else hit_target.id
        resolved_item_kind = item_kind or (
            "entity" if geometry is not None else "hit"
        )
        selection_id = f"{self._local_id(name)}_selection"
        if initial is None:
            initial_values: tuple[Any, ...] = ()
        elif multiple:
            if isinstance(initial, (str, bytes)):
                raise ValueError(
                    "selection(..., multiple=True) expects an iterable of values"
                )
            initial_values = tuple(initial)
        else:
            initial_values = (initial,)
        if resolved_item_kind == "entity":
            initial_values = tuple(str(value) for value in initial_values)
        self._add_binding(
            SpecBinding(
                selections=(
                    SelectionSpec(
                        id=selection_id,
                        target_type=target_type,
                        target_id=target_id,
                        item_kind=resolved_item_kind,
                        initial=initial_values,
                        multiple=multiple,
                    ),
                )
            )
        )
        return SelectionRef(
            selection_id,
            target_type=target_type,
            target_id=target_id,
            item_kind=resolved_item_kind,
            multiple=multiple,
        )

    def click(
        self,
        name: str,
        *,
        hit_target: HitTargetRef,
        result_kind: str = "hit",
        geometry_scope: GeometryRef | None = None,
        selection: SelectionRef | None = None,
    ) -> ClickRef:
        """Derive a typed value from a click on an authored hit route."""
        if not isinstance(hit_target, HitTargetRef):
            raise TypeError("click(...) hit_target must be a HitTargetRef")
        if geometry_scope is not None and not isinstance(geometry_scope, GeometryRef):
            raise TypeError("click(...) geometry_scope must be a GeometryRef")
        if selection is not None and not isinstance(selection, SelectionRef):
            raise TypeError("click(...) selection must be a SelectionRef")
        interaction_id = f"{self._local_id(name)}_click"
        self._add_binding(
            SpecBinding(
                clicks=(
                    ClickSpec(
                        id=interaction_id,
                        hit_target_id=hit_target.id,
                        result_kind=result_kind,
                        geometry_scope_id=(
                            None if geometry_scope is None else geometry_scope.id
                        ),
                        selection_id=None if selection is None else selection.id,
                    ),
                )
            )
        )
        return ClickRef(
            interaction_id,
            hit_target.id,
            str(result_kind).strip(),
            None if geometry_scope is None else geometry_scope.id,
        )

    def entity_click(
        self,
        name: str,
        *,
        geometry: GeometryRef,
        hit_target: HitTargetRef | None = None,
        selection: SelectionRef | None = None,
    ) -> EntityClickRef:
        """Declare a geometry click, optionally linked to selection state.

        The link supplies ordinary selection behavior when no backend tool
        consumes the click. Omitting it creates a pure click interaction for
        editor tools and other non-selection behaviors.
        """
        if not isinstance(geometry, GeometryRef):
            raise TypeError("entity_click(...) geometry must be a GeometryRef")
        target = self.hit_target(name) if hit_target is None else hit_target
        interaction = self.click(
            name,
            hit_target=target,
            result_kind="entity",
            geometry_scope=geometry,
            selection=selection,
        )
        return EntityClickRef(
            interaction.id,
            interaction.hit_target_id,
            interaction.result_kind,
            interaction.geometry_scope_id,
        )

    def hit_target(
        self,
        name: str,
    ) -> HitTargetRef:
        """Declare a renderer-local pick route with no semantic result policy."""
        target_id = f"{self._local_id(name)}_hit_target"
        self._add_binding(
            SpecBinding(
                hit_targets=(
                    HitTargetSpec(id=target_id),
                )
            )
        )
        return HitTargetRef(target_id)

    def on_click(self, interaction: ClickRef, fn: ClickHandler) -> None:
        """Attach backend behavior to one exact authored click interaction."""
        if not isinstance(interaction, ClickRef):
            raise TypeError("on_click(...) expects a ClickRef")
        if not callable(fn):
            raise TypeError("on_click(...) handler must be callable")
        self.__source._add_click_handler(
            ClickHandlerBinding(fn=fn, interaction_id=interaction.id)
        )

    def on_entity_click(
        self,
        interaction: EntityClickRef,
        fn: EntityClickHandler,
    ) -> None:
        """Attach backend behavior to one exact authored click interaction."""
        if not isinstance(interaction, EntityClickRef):
            raise TypeError("on_entity_click(...) expects an EntityClickRef")
        if not callable(fn):
            raise TypeError("on_entity_click(...) handler must be callable")
        self.__source._add_click_handler(
            ClickHandlerBinding(
                fn=lambda context, event: fn(context, str(event.value)),
                interaction_id=interaction.id,
                result_kind="entity",
            )
        )

    def pointer(
        self,
        name: str,
        *,
        hit_target: HitTargetRef,
        result_kind: str = "hit",
        geometry_scope: GeometryRef | None = None,
        enabled: Any = True,
        button: str = "primary",
    ) -> PointerInteractionRef:
        """Capture a pointer stream beginning on an authored hit route."""
        if not isinstance(hit_target, HitTargetRef):
            raise TypeError("pointer(...) hit_target must be a HitTargetRef")
        if geometry_scope is not None and not isinstance(
            geometry_scope, GeometryRef
        ):
            raise TypeError("pointer(...) geometry_scope must be a GeometryRef")
        return self._declare_pointer(
            name,
            hit_target_id=hit_target.id,
            result_kind=result_kind,
            geometry_scope_id=(
                None if geometry_scope is None else geometry_scope.id
            ),
            enabled=enabled,
            button=button,
        )

    def _declare_pointer(
        self,
        name: str,
        *,
        hit_target_id: str,
        result_kind: str,
        geometry_scope_id: str | None,
        enabled: Any,
        button: str,
    ) -> PointerInteractionRef:
        pointer_id = f"{self._local_id(name)}_pointer"
        resolved_kind = str(result_kind).strip()
        self._add_binding(
            SpecBinding(
                pointer_interactions=(
                    PointerInteractionSpec(
                        id=pointer_id,
                        hit_target_id=hit_target_id,
                        result_kind=resolved_kind,
                        geometry_scope_id=geometry_scope_id,
                        enabled=bind(enabled),
                        button=button,
                    ),
                )
            )
        )
        return PointerInteractionRef(
            pointer_id,
            hit_target_id,
            resolved_kind,
            geometry_scope_id,
        )

    def on_pointer(
        self,
        interaction: PointerInteractionRef,
        fn: PointerInteractionHandler,
    ) -> None:
        """Attach backend behavior to one exact captured pointer stream."""
        if not isinstance(interaction, PointerInteractionRef):
            raise TypeError("on_pointer(...) expects a PointerInteractionRef")
        if not callable(fn):
            raise TypeError("on_pointer(...) handler must be callable")
        self.__source._add_pointer_interaction_handler(
            PointerInteractionHandlerBinding(
                fn=fn,
                interaction_id=interaction.id,
            )
        )

    def entity_pointer(
        self,
        name: str,
        *,
        interaction: ClickRef | None = None,
        hit_target: HitTargetRef | None = None,
        geometry: GeometryRef | None = None,
        enabled: Any = True,
        button: str = "primary",
    ) -> EntityPointerRef:
        """Capture pointer gestures that begin on an authored entity hit route.

        ``enabled`` may be a control or value binding. When disabled, the host's
        ordinary camera gesture remains untouched. When enabled, only a press
        that actually hits the interaction's geometry captures the gesture.
        """
        if (interaction is None) == (hit_target is None):
            raise ValueError(
                "entity_pointer(...) requires exactly one of interaction= or hit_target="
            )
        if interaction is not None and not isinstance(interaction, ClickRef):
            raise TypeError("entity_pointer(...) interaction must be a ClickRef")
        if hit_target is not None and not isinstance(hit_target, HitTargetRef):
            raise TypeError("entity_pointer(...) hit_target must be a HitTargetRef")
        if geometry is not None and not isinstance(geometry, GeometryRef):
            raise TypeError("entity_pointer(...) geometry must be a GeometryRef")
        if interaction is not None:
            if (
                interaction.result_kind != "entity"
                or interaction.geometry_scope_id is None
            ):
                raise ValueError(
                    "entity_pointer(...) interaction must produce geometry-scoped entities"
                )
            geometry_id = interaction.geometry_scope_id
        else:
            if geometry is None:
                raise ValueError(
                    "entity_pointer(..., hit_target=...) requires geometry=..."
                )
            geometry_id = geometry.id
        target_id = (
            interaction.hit_target_id
            if interaction is not None
            else hit_target.id
        )
        pointer = self._declare_pointer(
            name,
            hit_target_id=target_id,
            result_kind="entity",
            geometry_scope_id=geometry_id,
            enabled=enabled,
            button=button,
        )
        return EntityPointerRef(
            pointer.id,
            pointer.hit_target_id,
            pointer.result_kind,
            pointer.geometry_scope_id,
        )

    def on_entity_pointer(
        self,
        interaction: EntityPointerRef,
        fn: PointerInteractionHandler,
    ) -> None:
        """Attach backend behavior to one exact captured pointer gesture."""
        if not isinstance(interaction, EntityPointerRef):
            raise TypeError("on_entity_pointer(...) expects an EntityPointerRef")
        if not callable(fn):
            raise TypeError("on_entity_pointer(...) handler must be callable")
        self.on_pointer(interaction, fn)

    def operator(
        self,
        kind: str,
        name: str,
        *,
        inputs: Mapping[str, DataRef],
        geometries: Mapping[str, GeometryRef] | None = None,
        properties: Mapping[str, Any] | None = None,
    ) -> DataRef:
        """Declare a neutral data-producing operator."""
        operator_id = f"{self._local_id(name)}_{slug(kind)}_operator"
        spec = OperatorSpec(
            id=operator_id,
            kind=kind,
            inputs={str(role): data._field_id for role, data in inputs.items()},
            geometries={
                str(role): geometry.id for role, geometry in (geometries or {}).items()
            },
            properties=_bind_tree(properties or {}),
        )
        self._add_binding(
            SpecBinding(
                operators=(spec,),
            )
        )
        return DataRef(_field_id=operator_id)

    def visual_contribution(
        self,
        kind: str,
        name: str,
        *,
        target: PanelRef,
        capability: str,
        inputs: Mapping[str, DataRef] | None = None,
        geometries: Mapping[str, GeometryRef] | None = None,
        hit_targets: Mapping[str, HitTargetRef] | None = None,
        selections: Mapping[str, SelectionRef] | None = None,
        properties: Mapping[str, Any] | None = None,
        max_refresh_hz: float | None = None,
    ) -> None:
        """Contribute neutral visual content into a capable target panel."""
        contribution_id = f"{self._local_id(name)}_{slug(kind)}_contribution"
        spec = VisualContributionSpec(
            id=contribution_id,
            kind=kind,
            capability=capability,
            inputs={
                str(role): data._field_id for role, data in (inputs or {}).items()
            },
            geometries={
                str(role): geometry.id
                for role, geometry in (geometries or {}).items()
            },
            hit_targets={
                str(role): hit_target.id
                for role, hit_target in (hit_targets or {}).items()
            },
            selections={
                str(role): selection.id
                for role, selection in (selections or {}).items()
            },
            properties=_bind_tree(properties or {}),
            max_refresh_hz=max_refresh_hz,
        )
        self._add_binding(
            SpecBinding(
                visual_contributions=(spec,),
                panel_contribution_ids={target.id: (contribution_id,)},
            )
        )

    def _add_binding(self, binding: Binding) -> None:
        self.__source._add_widget_binding(binding)

    def _add_series(self, binding: SeriesProducer) -> None:
        self.__source._add_series(binding)

    def _declare_field(self, **kwargs: Any) -> SnapshotProducer:
        return self.__source._declare_field(**kwargs)

    def _declare_grid_field(self, **kwargs: Any) -> SnapshotProducer:
        return self.__source._declare_grid_field(**kwargs)

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
