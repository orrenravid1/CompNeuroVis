from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from compneurovis.core.app_spec import (
    AppFragmentSpec,
    AppRef,
    app_ref,
    AppSpec,
    DEFAULT_FRAGMENT_ID,
    LayoutCatalog,
    LayoutSpec,
    PanelSpec,
    default_panel_grid,
)
from compneurovis.core.messages import Message, MessagePayload


@dataclass(frozen=True, slots=True)
class AppFragment:
    """A source-owned app fragment before final RunSpec assembly."""

    id: str
    fragment_spec: AppFragmentSpec
    actor: Any
    actor_id: str


def build_integrated_app_spec(
    fragments: tuple[AppFragment, ...] | list[AppFragment],
    *,
    title: str = "CompNeuroVis",
) -> AppSpec:
    """Build the global app shell from fragment-local catalogs.

    Fragment catalogs stay local. The integrated layout is the only global
    structure; its panels reference fragment-local views, controls, actions,
    and operators through AppRef.
    """

    panels: list[PanelSpec] = []
    panel_grid: list[tuple[str, ...]] = []
    metadata_fragments: list[Mapping[str, Any]] = []
    fragment_map = {fragment.id: fragment.fragment_spec for fragment in fragments}

    for fragment in fragments:
        layout = fragment.fragment_spec.active_layout()
        panel_id_map = {
            panel.id: _integrated_panel_id(fragment.id, panel.id)
            for panel in layout.panels
        }
        for panel in layout.panels:
            panels.append(_integrate_fragment_panel(panel, fragment.id))

        source_grid = layout.panel_grid or default_panel_grid(layout.panels)
        for row in source_grid:
            panel_grid.append(tuple(panel_id_map[panel_id] for panel_id in row))
        metadata_fragments.append(fragment.fragment_spec.metadata)

    return AppSpec(
        layout_catalog=LayoutCatalog.single(
            LayoutSpec(title=title, panels=tuple(panels), panel_grid=tuple(panel_grid))
        ),
        metadata={"fragments": tuple(metadata_fragments)},
        fragments=fragment_map,
    )


def tag_fragment_message(
    message: Message[MessagePayload],
    fragment_id: str,
) -> Message[MessagePayload]:
    tags = dict(message.tags)
    tags["fragment_id"] = fragment_id
    return Message(type=message.type, intent=message.intent, payload=message.payload, tags=tags)


def _refs(values: tuple[str | AppRef, ...], fragment_id: str) -> tuple[AppRef, ...]:
    return tuple(app_ref(value, fragment_id=fragment_id) for value in values)


def _integrated_panel_id(fragment_id: str, panel_id: str) -> str:
    return panel_id if fragment_id == DEFAULT_FRAGMENT_ID else f"{fragment_id}:{panel_id}"


def _integrate_fragment_panel(panel: PanelSpec, fragment_id: str) -> PanelSpec:
    """Apply the same fragment scope used by startup and live reconciliation."""

    return replace(
        panel,
        id=_integrated_panel_id(fragment_id, panel.id),
        view_ids=_refs(panel.view_ids, fragment_id),
        control_ids=_refs(panel.control_ids, fragment_id),
        contribution_ids=_refs(panel.contribution_ids, fragment_id),
    )


__all__ = [
    "AppFragment",
    "build_integrated_app_spec",
    "tag_fragment_message",
]
