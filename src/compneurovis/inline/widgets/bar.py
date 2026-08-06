"""Bar widget declaration through public authoring primitives."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Callable, TYPE_CHECKING

import numpy as np

from compneurovis.inline._ids import slug
from compneurovis.inline.refs import BarRef, DataRef
from compneurovis.inline.widgets.api import Widget
from compneurovis.inline.widgets.plotting import (
    declare_level_contributions,
    level_items,
    level_marker,
)

if TYPE_CHECKING:
    from compneurovis.inline.widgets.api import WidgetAuthoringContext


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
        category_dim = (
            self.by
            or (self.source._series_dim if self.source is not None else None)
            or "series"
        )
        owns_data = self.values is not None or self.read is not None
        unit = self.unit
        if owns_data:
            if self.source is not None:
                raise ValueError(
                    "bar(...) takes values=/read=, or source=..., not both"
                )
            labels = _category_labels(self.series, self.values, self.name)
            if self.read is not None:
                data = context.data(
                    self.name,
                    read=self.read,
                    labels=labels,
                    dim=category_dim,
                    unit=unit,
                )
            else:
                data = context.data(
                    self.name,
                    values=self.values,
                    labels=labels,
                    dim=category_dim,
                    unit=unit,
                )
        else:
            if self.source is None:
                raise ValueError(
                    "bar(...) requires values=..., read=..., or source=..."
                )
            data = self.source
            if data._unit is not None and unit is None:
                unit = data._unit
        if unit is not None and "y_unit" not in style:
            style["y_unit"] = unit

        title = style.pop("title", self.name)
        max_refresh_hz = style.pop("max_refresh_hz", None)
        style_levels = style.pop("levels", ())
        panel = context.view(
            "bar_plot",
            self.name,
            inputs={"data": data},
            properties={"category_dim": category_dim, **style},
            title=title,
            panel_id=self.panel_id or f"{slug(self.name)}-panel",
            max_refresh_hz=max_refresh_hz,
        )
        levels = tuple(
            level_marker(item, "vertical")
            for item in (
                *level_items(self.levels),
                *level_items(style_levels),
            )
        )
        declare_level_contributions(context, levels, target=panel)
        return BarRef(panel.id)


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


__all__ = ["Bar"]
