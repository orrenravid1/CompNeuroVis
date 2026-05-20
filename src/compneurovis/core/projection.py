from __future__ import annotations

import copy

from compneurovis.core.app import AppSpec, LayoutSpec
from compneurovis.core.field import Field


class AppProjection:
    """Actor-local read model derived from AppSpec plus runtime updates.

    Two members, two tiers:

    - ``spec``: a structural working copy of the startup declaration. Runtime
      structural updates fold here. These are spec-shaped replacements inside
      the projection; the declared AppSpec remains immutable.

    - ``fields``: the live value views, derived from the declaration's
      ``FieldSpec`` entries via ``materialize()``. FieldAppend/FieldReplace
      fold here. Field values do not live in AppSpec.
    """

    __slots__ = ("spec", "fields", "metadata", "active_layout_id")

    def __init__(self, seed: AppSpec) -> None:
        self.spec = copy.deepcopy(seed)
        self.fields: dict[str, Field] = {
            field_id: field_spec.materialize()
            for field_id, field_spec in seed.data.fields.items()
        }
        # Live metadata: seeded from the declaration, then folded by
        # AppMetadataPatch. The seed's AppSpec.metadata stays the declared
        # initial value.
        self.metadata: dict = dict(seed.metadata)
        # Live active-layout selection. LayoutCatalog.active is the declared
        # default; the current selection is projection state.
        self.active_layout_id: str = seed.layout_catalog.active

    def active_layout(self) -> LayoutSpec:
        return self.spec.layout_catalog.layouts[self.active_layout_id]


__all__ = ["AppProjection"]
