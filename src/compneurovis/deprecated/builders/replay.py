from __future__ import annotations

from dataclasses import replace
from functools import partial

from compneurovis.core import ActionSpec, AppSpec, PanelSpec, RunSpec, default_panel_grid
from compneurovis.backends import BackendBase
from compneurovis.core.app_spec import InteractionCatalog, LayoutCatalog, LayoutSpec, PANEL_KIND_CONTROLS
from compneurovis.core.messages import FieldReplace, Reset


class ReplayBackend(BackendBase):
    """Backend that replays a precomputed sequence of frame replacements."""

    def __init__(self, *, app_spec: AppSpec, field_id: str, frames, interval_live: bool = True):
        super().__init__()
        self.app_spec = app_spec
        self.field_id = field_id
        self.frames = list(frames)
        self.index = 0
        self.interval_live = interval_live

    def initialize(self, app_spec: AppSpec) -> None:
        pass

    def is_active(self) -> bool:
        return self.interval_live

    def tick(self) -> None:
        if not self.frames:
            return
        values, coords = self.frames[self.index]
        self.emit_update(FieldReplace(field_id=self.field_id, values=values, coords=coords))
        self.index = (self.index + 1) % len(self.frames)

    def handle(self, message) -> None:
        command = message.payload
        if isinstance(command, Reset):
            self.index = 0
            if not self.frames:
                return None
            values, coords = self.frames[0]
            self.emit_update(FieldReplace(field_id=self.field_id, values=values, coords=coords))
        return None


def build_replay_app(*, app_spec: AppSpec, field_id: str, frames) -> RunSpec:
    """Build an app that replays precomputed frames through ReplayBackend."""

    actions = dict(app_spec.interactions.actions)
    actions.setdefault("reset", ActionSpec("reset", "Reset", shortcuts=("Space",)))
    layouts = dict(app_spec.layout_catalog.layouts)
    layout = layouts[app_spec.layout_catalog.active]
    panels = list(layout.panels)
    controls_panel_index = next(
        (index for index, panel in enumerate(panels) if panel.kind == PANEL_KIND_CONTROLS),
        None,
    )
    if controls_panel_index is None:
        panels.append(
            PanelSpec(
                id="controls-panel",
                kind=PANEL_KIND_CONTROLS,
                action_ids=("reset",),
            )
        )
    else:
        panel = panels[controls_panel_index]
        panels[controls_panel_index] = replace(
            panel,
            action_ids=tuple(dict.fromkeys((*panel.action_ids, "reset"))),
        )
    layouts[app_spec.layout_catalog.active] = LayoutSpec(
        title=layout.title,
        panels=tuple(panels),
        panel_grid=default_panel_grid(tuple(panels)),
    )
    app_spec = AppSpec(
        data=app_spec.data,
        view_catalog=app_spec.view_catalog,
        interactions=InteractionCatalog(
            controls=app_spec.interactions.controls,
            actions=actions,
        ),
        layout_catalog=LayoutCatalog(
            layouts=layouts,
            active=app_spec.layout_catalog.active,
        ),
        metadata=app_spec.metadata,
    )

    return RunSpec(
        app_spec=app_spec,
        backend=partial(ReplayBackend, app_spec=app_spec, field_id=field_id, frames=frames),
        title=app_spec.layout_catalog.active_layout().title,
    )
