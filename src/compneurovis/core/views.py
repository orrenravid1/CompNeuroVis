from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from compneurovis.core._immutability import FrozenDict
from compneurovis.core.references import AppRef, freeze_ref_map
from compneurovis.core.specs import (
    PANEL_KIND_STANDALONE,
    IdentifiedSpec,
)
from compneurovis.core.values import freeze_binding_data

ValueOrBinding = Any


@dataclass(frozen=True, slots=True)
class ViewSpec(IdentifiedSpec):
    """Frontend-neutral canonical view declaration.

    ``kind`` selects a frontend renderer. ``inputs`` gives that renderer named
    data dependencies, while ``properties`` contains immutable presentation
    configuration and runtime value bindings.

    This is the universal authored view: every widget -- built-in or third-party --
    lowers to one of these. The typed render-configs a frontend rebuilds from it
    (line plots, surfaces, morphologies, …) live with that frontend's widget impls,
    not here; core carries only the canonical view contract.
    """

    title: ValueOrBinding = ""
    kind: str = ""
    inputs: Mapping[str, str | AppRef] = field(default_factory=FrozenDict)
    geometries: Mapping[str, str | AppRef] = field(default_factory=FrozenDict)
    selections: Mapping[str, str | AppRef] = field(default_factory=FrozenDict)
    properties: Mapping[str, Any] = field(default_factory=FrozenDict)
    max_refresh_hz: float | None = None
    # The panel category the author places this view in — declared, not inferred.
    panel_kind: str = PANEL_KIND_STANDALONE

    def __post_init__(self) -> None:
        kind = str(self.kind).strip()
        if not kind:
            raise ValueError("ViewSpec.kind cannot be empty")
        object.__setattr__(self, "kind", kind)
        panel_kind = str(self.panel_kind).strip()
        if not panel_kind:
            raise ValueError("ViewSpec.panel_kind cannot be empty")
        object.__setattr__(self, "panel_kind", panel_kind)
        object.__setattr__(
            self,
            "title",
            freeze_binding_data(self.title, path="ViewSpec.title"),
        )
        object.__setattr__(
            self,
            "inputs",
            freeze_ref_map(self.inputs, path="ViewSpec.inputs"),
        )
        object.__setattr__(
            self,
            "geometries",
            freeze_ref_map(
                self.geometries,
                path="ViewSpec.geometries",
            ),
        )
        object.__setattr__(
            self,
            "selections",
            freeze_ref_map(
                self.selections,
                path="ViewSpec.selections",
            ),
        )
        object.__setattr__(
            self,
            "properties",
            freeze_binding_data(self.properties, path="ViewSpec.properties"),
        )
