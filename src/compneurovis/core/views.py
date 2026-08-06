from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from compneurovis.core._immutability import FrozenDict
from compneurovis.core.references import AppRef, freeze_ref_map
from compneurovis.core.specs import (
    PANEL_KIND_EXTENSION,
    IdentifiedSpec,
)

ValueOrBinding = Any


@dataclass(frozen=True, slots=True)
class ViewSpec(IdentifiedSpec):
    title: ValueOrBinding = ""


@dataclass(frozen=True, slots=True)
class ExtensionViewSpec(ViewSpec):
    """Frontend-neutral declaration for an installed view extension.

    ``kind`` selects a frontend renderer. ``inputs`` gives that renderer named
    data dependencies, while ``properties`` contains immutable presentation
    configuration and runtime value bindings.

    This is the universal authored view: every widget -- built-in or third-party --
    lowers to one of these. The typed render-configs a frontend rebuilds from it
    (line plots, surfaces, morphologies, …) live with that frontend's widget impls,
    not here; core carries only the extension mechanism.
    """

    kind: str = ""
    inputs: Mapping[str, str | AppRef] = field(default_factory=FrozenDict)
    geometries: Mapping[str, str | AppRef] = field(default_factory=FrozenDict)
    selections: Mapping[str, str | AppRef] = field(default_factory=FrozenDict)
    properties: Mapping[str, Any] = field(default_factory=FrozenDict)
    max_refresh_hz: float | None = None
    # The panel category the author places this view in — declared, not inferred.
    panel_kind: str = PANEL_KIND_EXTENSION

    def __post_init__(self) -> None:
        if not self.kind.strip():
            raise ValueError("ExtensionViewSpec.kind cannot be empty")
        object.__setattr__(
            self,
            "inputs",
            freeze_ref_map(self.inputs, path="ExtensionViewSpec.inputs"),
        )
        object.__setattr__(
            self,
            "geometries",
            freeze_ref_map(
                self.geometries,
                path="ExtensionViewSpec.geometries",
            ),
        )
        object.__setattr__(
            self,
            "selections",
            freeze_ref_map(
                self.selections,
                path="ExtensionViewSpec.selections",
            ),
        )
        object.__setattr__(self, "properties", FrozenDict(self.properties))


@dataclass(frozen=True, slots=True)
class LevelMarker:
    """A reference line on a 2D plot, positioned by a value or binding.

    ``orientation="horizontal"`` draws y = value (e.g. a threshold on a trace);
    ``"vertical"`` draws x = value. ``value`` may be a number or a ValueBindingSpec
    so the line tracks a control/derived value live.

    NOTE: plot-specific, not universal. It sits in core only because it is *authored*
    (``inline/widgets/plotting.py`` builds it; it travels in a line/bar widget's
    ``properties``) while its renderer lives in the frontend -- two sibling trees
    whose shared type is forced into their common ancestor. It leaves core with the
    other authored per-widget specs (morphology geometry) in
    the widget-as-package restructure; it can't move to the frontend now without
    making the authoring layer import rendering.
    """

    value: ValueOrBinding
    orientation: str = "horizontal"
    color: ValueOrBinding = "#d62728"
    width: float = 2.0
    label: str = ""
