"""Scene3D panel lifecycle."""

from __future__ import annotations

import time
from typing import Any

from compneurovis.core import PanelSpec, app_ref
from compneurovis.frontends.vispy.bindings import resolve_binding
from compneurovis.frontends.vispy.panels.view3d import IndependentCanvas3DHostPanel
from compneurovis.frontends.vispy.registries.panel_hosts import PanelHostContext
from compneurovis.frontends.vispy.registries.render_configs import view_render_config
from compneurovis.frontends.vispy.registries.scene_layers import (
    SceneLayerRefreshContext,
    scene_layer_for_target,
    scene_layer_target_kinds,
    target_refresh_order,
)
from .contributions import _build_contribution_renderers, _refresh_contribution

DEFAULT_SCENE_3D_MAX_REFRESH_HZ = 8.0

class Scene3DPanelLifecycle:
    compact_when_last = False

    def __init__(self, context: PanelHostContext, panel: PanelSpec):
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
    def inspection_surfaces(self):
        return {"viewports": {self.view_id: self.host.viewport}}

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


__all__ = ["Scene3DPanelLifecycle"]
