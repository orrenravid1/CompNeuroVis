"""Visual-contribution mounting shared by capable panel hosts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from compneurovis.core import PanelSpec, app_ref
from compneurovis.frontends.vispy.bindings import resolve_binding
from compneurovis.frontends.vispy.registries.panel_hosts import PanelHostContext
from compneurovis.frontends.vispy.registries.visual_contributions import (
    VisualContributionHostContext,
    create_visual_contribution_renderer,
)


def _resolve_properties(value: Any, values: dict, fragment_id: str) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _resolve_properties(item, values, fragment_id)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return tuple(_resolve_properties(item, values, fragment_id) for item in value)
    if isinstance(value, list):
        return [_resolve_properties(item, values, fragment_id) for item in value]
    return resolve_binding(value, values, fragment_id)


def _build_contribution_renderers(
    context: PanelHostContext,
    panel: PanelSpec,
    host: Any,
    view_id: Any = None,
) -> dict[Any, Any]:
    renderers: dict[Any, Any] = {}
    if not panel.contribution_ids:
        return renderers
    capabilities = tuple(
        getattr(host, "visual_contribution_capabilities", ())
    )
    surface = getattr(host, "visual_contribution_surface", None)
    for contribution_id in panel.contribution_ids:
        contribution_ref = app_ref(contribution_id)
        spec = context.app_spec.visual_contribution(contribution_ref)
        if spec is None:
            raise LookupError(
                f"Panel {panel.id!r} references missing visual contribution "
                f"{str(contribution_ref)!r}"
            )
        if spec.capability not in capabilities:
            supported = ", ".join(repr(item) for item in capabilities)
            suffix = f" Supported capabilities are {supported}." if supported else ""
            raise LookupError(
                f"Panel {panel.id!r} does not expose capability "
                f"{spec.capability!r} required by visual contribution "
                f"{spec.id!r}.{suffix}"
            )
        renderer_context = VisualContributionHostContext(
            capability=spec.capability,
            panel_id=panel.id,
            view_id=view_id,
            host=host,
            surface=surface,
        )
        renderers[contribution_ref] = create_visual_contribution_renderer(
            spec, renderer_context
        )
    return renderers


def _refresh_contribution(
    context: PanelHostContext,
    contribution_ref: Any,
    renderer: Any,
) -> None:
    spec = context.app_spec.visual_contribution(contribution_ref)
    if spec is None:
        return
    fragment_id = app_ref(contribution_ref).fragment_id
    values = context.values_for_fragment(fragment_id)
    inputs = {
        role: context.resolve_input(input_id, fragment_id, values)
        for role, input_id in spec.inputs.items()
    }
    geometries = {
        role: context.app_spec.geometry(
            app_ref(geometry_id, fragment_id=fragment_id)
        )
        for role, geometry_id in spec.geometries.items()
    }
    selections = {
        role: values.get(
            app_ref(selection_id, fragment_id=fragment_id),
            (),
        )
        for role, selection_id in spec.selections.items()
    }
    properties = _resolve_properties(spec.properties, values, fragment_id)
    renderer.refresh(
        spec,
        inputs,
        geometries,
        selections,
        properties,
        values,
    )


