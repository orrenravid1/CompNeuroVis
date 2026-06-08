"""
scratch/sine_wave.py — minimal functional example using the new ActorSpec/RunSpec API.

Run: python scratch/sine_wave.py
"""
from __future__ import annotations

import math

import numpy as np

from compneurovis import (
    ActorRole,
    ActorSpec,
    AppSpec,
    DataCatalog,
    Field,
    LayoutCatalog,
    LayoutSpec,
    LinePlotViewSpec,
    PanelSpec,
    RunSpec,
    ViewCatalog,
    run_app,
)
from compneurovis.backends import BackendBase
from compneurovis.backends.host import BackendHost
from compneurovis.core.actor_launchers import ActorProcess
from compneurovis.core.messages import FieldAppend
from compneurovis.frontends import VispyFrontendHost, VispyFrontendWindow
from compneurovis.transports import pipe_transport

TITLE = "Sine wave"
TIME_DIM = "time"
SERIES_DIM = "series"
FIELD_ID = "sine"
VIEW_ID = "sine_plot"
MAX_SAMPLES = 600
DT_MS = 16.0
FREQ_HZ = 0.5


def initial_app_spec() -> AppSpec:
    field = Field(
        id=FIELD_ID,
        values=np.array([[0.0]], dtype=np.float32),
        dims=(SERIES_DIM, TIME_DIM),
        coords={
            SERIES_DIM: np.array(["sine"]),
            TIME_DIM: np.array([0.0], dtype=np.float32),
        },
        unit="a.u.",
    )
    view = LinePlotViewSpec(
        id=VIEW_ID,
        title=TITLE,
        field_id=FIELD_ID,
        x_dim=TIME_DIM,
        series_dim=SERIES_DIM,
        x_label="Time",
        x_unit="ms",
        y_label="Amplitude",
        rolling_window=4000.0,
        trim_to_rolling_window=True,
        y_min=-1.1,
        y_max=1.1,
    )
    return AppSpec(
        data=DataCatalog(fields={FIELD_ID: field}),
        view_catalog=ViewCatalog(views={VIEW_ID: view}),
        layout_catalog=LayoutCatalog.single(
            LayoutSpec(
                title=TITLE,
                panels=(PanelSpec(id="main", kind="line_plot", view_ids=(VIEW_ID,)),),
            )
        ),
    )


class SineBackend(BackendBase):
    def __init__(self) -> None:
        super().__init__()
        self._t_ms = 0.0

    def initialize(self, app_spec: AppSpec) -> None:
        self._t_ms = 0.0

    def advance(self) -> None:
        self._t_ms += DT_MS
        value = math.sin(2 * math.pi * FREQ_HZ * self._t_ms / 1000.0)
        self.emit_update(
            FieldAppend(
                field_id=FIELD_ID,
                append_dim=TIME_DIM,
                values=np.array([[value]], dtype=np.float32),
                coord_values=np.array([self._t_ms], dtype=np.float32),
                max_length=MAX_SAMPLES,
            )
        )

    def handle(self, message) -> None:
        pass

    def idle_sleep(self) -> float:
        return DT_MS / 1000.0


run_app(
    RunSpec(
        app_spec=initial_app_spec(),
        actors=[
            ActorSpec(
                id="backend",
                role=ActorRole.BACKEND,
                host_source=lambda runtime, ch: ActorProcess(
                    actor_source=SineBackend,
                    app_spec=runtime.app_spec,
                    channel=ch,
                    host_class=BackendHost,
                    diagnostics=runtime.diagnostics,
                ),
            ),
            ActorSpec(
                id="frontend",
                role=ActorRole.FRONTEND,
                host_source=lambda runtime, ch: VispyFrontendHost(
                    actor_source=lambda: VispyFrontendWindow(title=TITLE),
                    runtime=runtime,
                    channel=ch,
                ),
                runs_in_foreground=True,
            ),
        ],
        transport=pipe_transport("backend", "frontend"),
    )
)
