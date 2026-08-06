"""Bar widget declaration and AppSpec lowering."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

import numpy as np

from compneurovis.core.app_spec import PANEL_KIND_EXTENSION, PanelSpec
from compneurovis.core.views import ExtensionViewSpec
from compneurovis.inline._ids import slug
from compneurovis.inline.compiler import FieldInput, WidgetContribution
from compneurovis.inline.refs import BarRef, DataRef, bind
from compneurovis.inline.widgets.api import Widget
from compneurovis.inline.widgets.plotting import (
    level_contributions,
    level_items,
    level_marker,
)

if TYPE_CHECKING:
    from compneurovis.inline.widgets.api import WidgetAuthoringContext


@dataclass
class BarBinding:
    field_id: str
    view_id: str
    panel_id: str
    title: Any
    category_dim: str | None = "series"
    levels: Sequence[Any] = ()
    field_builders: tuple[FieldInput, ...] = ()
    style: Mapping[str, Any] = field(default_factory=dict)

    def contribution(self, backend: Any = None) -> WidgetContribution:
        levels = self.level_specs()
        visual_contributions = level_contributions(
            levels, view_id=self.view_id
        )
        return WidgetContribution(
            fields=tuple(
                item(backend) if callable(item) else item
                for item in self.field_builders
            ),
            views=(self.view_spec(),),
            visual_contributions=visual_contributions,
            panel_contribution_ids=(
                {self.panel_id: tuple(spec.id for spec in visual_contributions)}
                if visual_contributions
                else {}
            ),
            panel=self.panel_spec(),
        )

    def level_specs(self):
        style_levels = self.style.get("levels", ())
        return tuple(
            level_marker(item, "vertical")
            for item in (*level_items(self.levels), *level_items(style_levels))
        )

    def view_spec(self) -> ExtensionViewSpec:
        # A bar is a first-class extension view (kind="bar_plot"), rendered through
        # the same registry a third-party widget uses -- no native panel kind.
        kwargs = {key: bind(value) for key, value in self.style.items()}
        kwargs.pop("levels", None)
        max_refresh_hz = kwargs.pop("max_refresh_hz", None)
        return ExtensionViewSpec(
            id=self.view_id,
            title=bind(self.title),
            kind="bar_plot",
            inputs={"data": self.field_id},
            properties={
                "category_dim": self.category_dim,
                **kwargs,
            },
            max_refresh_hz=max_refresh_hz,
            panel_kind=PANEL_KIND_EXTENSION,
        )

    def panel_spec(self) -> PanelSpec:
        return PanelSpec(
            id=self.panel_id,
            kind=PANEL_KIND_EXTENSION,
            view_ids=(self.view_id,),
        )


@dataclass(frozen=True, slots=True)
class Bar(Widget[BarRef]):
    """Reusable bar widget accepted by ``source.add()``."""

    name: str
    values: Any = None
    read: Callable[[], Any] | None = None
    source: DataRef | None = None
    series: Sequence[str] | None = None
    by: str | None = None
    unit: str | None = None
    levels: Sequence[Any] = ()
    panel_id: str | None = None
    style: Mapping[str, Any] = field(default_factory=dict)

    def declare(self, context: WidgetAuthoringContext) -> BarRef:
        style = dict(self.style)
        name_slug = slug(self.name)
        panel_id = self.panel_id or f"{name_slug}-panel"
        category_dim = (
            self.by
            or (self.source._series_dim if self.source is not None else None)
            or "series"
        )
        owns_data = self.values is not None or self.read is not None
        field_builders: tuple[FieldInput, ...] = ()
        unit = self.unit
        if owns_data:
            if self.source is not None:
                raise ValueError(
                    "bar(...) takes values=/read=, or source=..., not both"
                )
            binding = context._declare_field(
                field_id=f"{name_slug}_field",
                dim=category_dim,
                labels=_category_labels(self.series, self.values, self.name),
                values=self.values,
                read=self.read,
                unit=unit,
            )
            resolved_field_id = binding.field_id
            field_builders = (lambda backend, _binding=binding: _binding.field_spec(),)
        else:
            resolved_field_id = (
                self.source._field_id if self.source is not None else None
            )
            if resolved_field_id is None:
                raise ValueError(
                    "bar(...) requires values=..., read=..., or source=..."
                )
            if (
                self.source is not None
                and self.source._unit is not None
                and unit is None
            ):
                unit = self.source._unit
        if unit is not None and "y_unit" not in style:
            style["y_unit"] = unit
        context._add_binding(
            BarBinding(
                field_id=resolved_field_id,
                view_id=f"{name_slug}_bar",
                panel_id=panel_id,
                title=style.pop("title", self.name),
                category_dim=category_dim,
                levels=self.levels,
                field_builders=field_builders,
                style=style,
            )
        )
        return BarRef(panel_id)


def _category_labels(
    series: Sequence[str] | None,
    values: Any,
    name: str,
) -> tuple[str, ...]:
    if series is not None:
        return tuple(str(item) for item in series)
    if values is None:
        raise ValueError(
            f"bar({name!r}) with read=... requires series=(...) category labels"
        )
    return tuple(str(index) for index in range(np.asarray(values).reshape(-1).size))


__all__ = ["BarBinding", "Bar"]
