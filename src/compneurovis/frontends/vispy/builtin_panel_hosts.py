"""Built-in panel hosts implemented through the public lifecycle contract."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from compneurovis.core import ExtensionViewSpec, PanelSpec, app_ref
from compneurovis.core.app_spec import PANEL_KIND_EXTENSION
from compneurovis.frontends.vispy.panel_hosts import (
    PanelHostContext,
    register_panel_host,
)
from compneurovis.frontends.vispy.panels.controls import ControlsHostPanel, ControlsPanel
from compneurovis.frontends.vispy.panels.view3d import IndependentCanvas3DHostPanel
from compneurovis.frontends.vispy.render_config import view_render_config
from compneurovis.frontends.vispy.renderers.registry import create_host
from compneurovis.frontends.vispy.refresh_planning import RefreshTarget
from compneurovis.frontends.vispy.view_inputs.bindings import resolve_binding
from compneurovis.frontends.vispy.view3d.visuals import (
    SceneLayerRefreshContext,
    scene_layer_for_target,
    scene_layer_target_kinds,
    target_refresh_order,
)
from compneurovis.frontends.vispy.visual_contributions import (
    VisualContributionHostContext,
    create_visual_contribution_renderer,
)

DEFAULT_SCENE_3D_MAX_REFRESH_HZ = 8.0
DEFAULT_EXTENSION_MAX_REFRESH_HZ = 15.0


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
    view_id: Any,
) -> dict[Any, Any]:
    renderers: dict[Any, Any] = {}
    if not panel.contribution_ids:
        return renderers
    capabilities = tuple(
        getattr(host, "visual_contribution_capabilities", ())
    )
    surface = getattr(host, "visual_contribution_surface", None)
    fragment_id = app_ref(view_id).fragment_id
    for contribution_id in panel.contribution_ids:
        contribution_ref = app_ref(
            contribution_id, fragment_id=fragment_id
        )
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


class ControlsPanelLifecycle:
    compact_when_last = True

    def __init__(self, context: PanelHostContext, panel: PanelSpec):
        self.context = context
        self.panel = panel
        self.controls_panel = ControlsPanel(
            context.control_changed, context.action_invoked
        )
        self.host = ControlsHostPanel(
            self.controls_panel,
            panel_id=panel.id,
            title=panel.title or "Controls",
        )
        self._pending = False

    @property
    def widget(self):
        return self.host

    @property
    def viewports(self):
        return {}

    @property
    def controls_surface(self):
        return self.controls_panel

    @property
    def has_pending_refresh(self) -> bool:
        return self._pending

    def accepts_refresh_target(self, target: Any) -> bool:
        return target == RefreshTarget.CONTROLS

    def queue_refresh(self, target: Any) -> None:
        if self.accepts_refresh_target(target):
            self._pending = True

    def flush_refreshes(self, **_: Any) -> int:
        if not self._pending:
            return 0
        controls, actions = self.context.controls_and_actions(self.panel.id)
        self.host.set_section_title(
            has_controls=bool(controls), has_actions=bool(actions)
        )
        self.controls_panel.set_controls(
            controls, actions, self.context.value_snapshot()
        )
        self._pending = False
        return 1

    def update_visibility(self) -> None:
        controls, actions = self.context.controls_and_actions(self.panel.id)
        self.host.setVisible(bool(controls or actions))

    def dispose(self) -> None:
        self._pending = False


class ExtensionPanelLifecycle:
    compact_when_last = False

    def __init__(self, context: PanelHostContext, panel: PanelSpec):
        if len(panel.view_ids) != 1:
            raise ValueError(
                f"Extension panel {panel.id!r} must contain exactly one view id"
            )
        self.context = context
        self.panel = panel
        self.view_id = panel.view_ids[0]
        view = context.app_spec.view(self.view_id)
        if not isinstance(view, ExtensionViewSpec):
            raise TypeError(f"Extension panel {panel.id!r} has no extension view")
        self.host = create_host(
            view,
            panel_id=panel.id,
            view_id=self.view_id,
            title=panel.title or str(view.title or self.view_id),
        )
        self._contribution_renderers = _build_contribution_renderers(
            context, panel, self.host, self.view_id
        )
        self._pending_contributions: set[Any] = set()
        self._pending = False
        self._last_refresh_s: float | None = None

    @property
    def widget(self):
        return self.host

    @property
    def viewports(self):
        return {}

    @property
    def controls_surface(self):
        return None

    @property
    def has_pending_refresh(self) -> bool:
        return self._pending or bool(self._pending_contributions)

    def accepts_refresh_target(self, target: Any) -> bool:
        return (
            target.kind == "extension" and target.view_id == self.view_id
        ) or (
            target.kind == "visual_contribution"
            and target.view_id == self.view_id
            and target.contribution_id in self._contribution_renderers
        )

    def queue_refresh(self, target: Any) -> None:
        if not self.accepts_refresh_target(target):
            return
        if target.kind == "visual_contribution":
            self._pending_contributions.add(target.contribution_id)
        else:
            self._pending = True

    def _interval_s(self, view: ExtensionViewSpec) -> float | None:
        hz = (
            view.max_refresh_hz
            if view.max_refresh_hz is not None
            else DEFAULT_EXTENSION_MAX_REFRESH_HZ
        )
        return None if float(hz) <= 0 else 1.0 / float(hz)

    def flush_refreshes(
        self,
        *,
        force: bool = False,
        now: float | None = None,
        refresh_deadline_s: float | None = None,
    ) -> int:
        if not self.has_pending_refresh:
            return 0
        if refresh_deadline_s is not None and time.monotonic() >= refresh_deadline_s:
            return 0
        current_time = time.monotonic() if now is None else now
        view = self.context.app_spec.view(self.view_id)
        if not isinstance(view, ExtensionViewSpec):
            self._pending = False
            return 0
        interval = self._interval_s(view)
        if (
            not force
            and interval is not None
            and self._last_refresh_s is not None
            and current_time - self._last_refresh_s < interval
        ):
            return 0
        view_ref = app_ref(self.view_id)
        values = self.context.values_for_fragment(view_ref.fragment_id)
        inputs = {
            role: self.context.resolve_input(field_id, view_ref.fragment_id, values)
            for role, field_id in view.inputs.items()
        }
        properties = _resolve_properties(view.properties, values, view_ref.fragment_id)
        if self._pending:
            self.host.refresh(view, inputs, properties, values)
        for contribution_ref in sorted(
            self._pending_contributions, key=str
        ):
            _refresh_contribution(
                self.context,
                contribution_ref,
                self._contribution_renderers[contribution_ref],
            )
        self._last_refresh_s = current_time
        self._pending = False
        self._pending_contributions.clear()
        return 1

    def update_visibility(self) -> None:
        self.host.setVisible(True)

    def dispose(self) -> None:
        self._pending = False
        self._pending_contributions.clear()
        for renderer in self._contribution_renderers.values():
            renderer.clear()


class Scene3DPanelLifecycle:
    compact_when_last = False

    def __init__(self, context: PanelHostContext, panel: PanelSpec):
        if panel.host_kind != "independent_canvas":
            raise LookupError(
                f"Scene host {panel.id!r} has unsupported host_kind "
                f"{panel.host_kind!r}"
            )
        if len(panel.view_ids) != 1:
            raise ValueError(
                f"Scene3D panel {panel.id!r} must contain exactly one view id"
            )
        self.context = context
        self.panel = panel
        self.view_id = panel.view_ids[0]
        view = view_render_config(context.app_spec.view(self.view_id))
        camera = (
            getattr(view, "camera_distance", 200.0),
            getattr(view, "camera_elevation", 30.0),
            getattr(view, "camera_azimuth", 30.0),
        )
        self.host = IndependentCanvas3DHostPanel(
            panel=panel,
            visual_kind=view.kind,
            title=panel.title or str(self.view_id),
            camera=camera,
            on_entity_selected=context.entity_selected,
        )
        self._contribution_renderers = _build_contribution_renderers(
            context, panel, self.host, self.view_id
        )
        self._pending_contributions: set[Any] = set()
        self._pending_kinds: set[str] = set()
        self._last_refresh_s: float | None = None

    @property
    def widget(self):
        return self.host

    @property
    def viewport(self):
        return self.host.viewport

    @property
    def viewports(self):
        return {self.view_id: self.host.viewport}

    @property
    def controls_surface(self):
        return None

    @property
    def has_pending_refresh(self) -> bool:
        return bool(self._pending_kinds or self._pending_contributions)

    def accepts_refresh_target(self, target: Any) -> bool:
        return (
            target.view_id == self.view_id
            and target.kind in scene_layer_target_kinds()
        ) or (
            target.view_id == self.view_id
            and target.kind == "visual_contribution"
            and target.contribution_id in self._contribution_renderers
        )

    def queue_refresh(self, target: Any) -> None:
        if not self.accepts_refresh_target(target):
            return
        if target.kind == "visual_contribution":
            self._pending_contributions.add(target.contribution_id)
        else:
            self._pending_kinds.add(target.kind)

    def _interval_s(self, view: Any) -> float | None:
        hz = getattr(view, "max_refresh_hz", None)
        value = float(DEFAULT_SCENE_3D_MAX_REFRESH_HZ if hz is None else hz)
        return None if value <= 0 else 1.0 / value

    def flush_refreshes(
        self,
        *,
        force: bool = False,
        now: float | None = None,
        refresh_deadline_s: float | None = None,
    ) -> int:
        if not self.has_pending_refresh:
            return 0
        if refresh_deadline_s is not None and time.monotonic() >= refresh_deadline_s:
            return 0
        current_time = time.monotonic() if now is None else now
        view = view_render_config(self.context.app_spec.view(self.view_id))
        if (
            not force
            and self._last_refresh_s is not None
            and (interval := self._interval_s(view)) is not None
            and current_time - self._last_refresh_s < interval
        ):
            return 0
        ctx = SceneLayerRefreshContext(
            app_spec=self.context.app_spec,
            values=self.context.value_snapshot(),
            view_id=self.view_id,
            fields=self.context.fields(),
            active_layout=self.context.active_layout(),
        )
        for kind in sorted(self._pending_kinds, key=target_refresh_order):
            layer_key = scene_layer_for_target(kind)
            if layer_key is None:
                continue
            visual = self.host.activate_visual(self.view_id, layer_key, view=view)
            if visual is not None:
                visual.refresh_for_target(kind, view, ctx)
        for contribution_ref in sorted(
            self._pending_contributions, key=str
        ):
            _refresh_contribution(
                self.context,
                contribution_ref,
                self._contribution_renderers[contribution_ref],
            )
        self.host.set_background(
            resolve_binding(
                getattr(view, "background_color", "white"),
                self.context.value_snapshot(),
                app_ref(self.view_id).fragment_id,
            )
        )
        primary = self.host.visual_for_kind(view.kind)
        refresh_overlays = getattr(primary, "refresh_overlays", None)
        if refresh_overlays is None:
            self.host.clear_colorbar()
        else:
            refresh_overlays(self.host, view, ctx)
        self.host.commit()
        self._last_refresh_s = current_time
        self._pending_kinds.clear()
        self._pending_contributions.clear()
        return 1

    def update_visibility(self) -> None:
        self.host.setVisible(True)

    def dispose(self) -> None:
        self._pending_kinds.clear()
        self._pending_contributions.clear()
        for renderer in self._contribution_renderers.values():
            renderer.clear()
        self.host.clear()


def register_builtin_panel_hosts() -> None:
    register_panel_host("controls", ControlsPanelLifecycle)
    register_panel_host(PANEL_KIND_EXTENSION, ExtensionPanelLifecycle)
    register_panel_host("scene_3d", Scene3DPanelLifecycle)


__all__ = [
    "ControlsPanelLifecycle",
    "ExtensionPanelLifecycle",
    "Scene3DPanelLifecycle",
    "register_builtin_panel_hosts",
]
