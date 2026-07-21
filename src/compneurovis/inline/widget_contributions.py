"""Typed compiler boundary between source widgets and canonical app specs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol, TypeAlias

from compneurovis.core.app_spec import PanelSpec
from compneurovis.core.controls import ControlSpec
from compneurovis.core.field import FieldSpec
from compneurovis.core.geometry import GeometrySpec
from compneurovis.core.operators import OperatorSpec
from compneurovis.core.views import ViewSpec


FieldInput: TypeAlias = FieldSpec | Callable[[Any], FieldSpec]
GeometryInput: TypeAlias = GeometrySpec | Callable[[Any], GeometrySpec]
ViewInput: TypeAlias = ViewSpec | Callable[[Any], ViewSpec]


@dataclass(frozen=True, slots=True)
class WidgetContribution:
    """Canonical specs emitted by one source-level widget."""

    fields: tuple[FieldSpec, ...] = ()
    geometries: tuple[GeometrySpec, ...] = ()
    views: tuple[ViewSpec, ...] = ()
    operators: tuple[OperatorSpec, ...] = ()
    controls: tuple[ControlSpec, ...] = ()
    panel: PanelSpec | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", tuple(self.fields))
        object.__setattr__(self, "geometries", tuple(self.geometries))
        object.__setattr__(self, "views", tuple(self.views))
        object.__setattr__(self, "operators", tuple(self.operators))
        object.__setattr__(self, "controls", tuple(self.controls))


class WidgetBinding(Protocol):
    """Internal compiler input that emits one typed contribution."""

    def contribution(self, backend: Any = None) -> WidgetContribution:
        """Build canonical specs, optionally using a source backend."""


@dataclass
class SpecWidget:
    """Contribution assembled from canonical specs or backend-aware builders."""

    field_builders: tuple[FieldInput, ...] = ()
    geometries: tuple[GeometryInput, ...] = ()
    views: tuple[ViewInput, ...] = ()
    panel: PanelSpec | None = None
    controls: tuple[ControlSpec, ...] = ()

    def contribution(self, backend: Any = None) -> WidgetContribution:
        return WidgetContribution(
            fields=tuple(
                item(backend) if callable(item) else item
                for item in self.field_builders
            ),
            geometries=tuple(
                item(backend) if callable(item) else item
                for item in self.geometries
            ),
            views=tuple(
                item(backend) if callable(item) else item
                for item in self.views
            ),
            panel=self.panel,
            controls=self.controls,
        )


__all__ = [
    "FieldInput",
    "GeometryInput",
    "SpecWidget",
    "ViewInput",
    "WidgetBinding",
    "WidgetContribution",
]
