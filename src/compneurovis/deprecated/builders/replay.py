from __future__ import annotations

from functools import partial

from compneurovis.core import ActionSpec, AppSpec, PanelSpec, RunSpec, default_panel_grid
from compneurovis.backends import BackendBase
from compneurovis.core.app import PANEL_KIND_CONTROLS
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

    app_spec.interactions.actions.setdefault("reset", ActionSpec("reset", "Reset", shortcuts=("Space",)))
    layout = app_spec.active_layout()
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
        panels[controls_panel_index] = PanelSpec(
            id=panel.id,
            kind=panel.kind,
            view_ids=panel.view_ids,
            control_ids=panel.control_ids,
            action_ids=tuple(dict.fromkeys((*panel.action_ids, "reset"))),
            operator_ids=panel.operator_ids,
            host_kind=panel.host_kind,
            title=panel.title,
            camera_distance=panel.camera_distance,
            camera_elevation=panel.camera_elevation,
            camera_azimuth=panel.camera_azimuth,
        )
    layout.replace_panels(tuple(panels), default_panel_grid(tuple(panels)))

    return RunSpec(
        app_spec=app_spec,
        backend=partial(ReplayBackend, app_spec=app_spec, field_id=field_id, frames=frames),
        title=app_spec.active_layout().title,
    )
