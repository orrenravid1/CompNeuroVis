from __future__ import annotations

import time

import numpy as np

from compneurovis.core import (
    AppSpec,
    DataCatalog,
    FieldSpec,
    InteractionCatalog,
    LayoutCatalog,
    LayoutSpec,
    LinePlotViewSpec,
    MorphologyGeometrySpec,
    MorphologyViewSpec,
    PanelSpec,
    StateBindingSpec,
    ViewCatalog,
)
from compneurovis.core.app_spec import PANEL_KIND_CONTROLS, PANEL_KIND_LINE_PLOT, PANEL_KIND_VIEW_3D


class NeuronAppSpecBuilder:
    """Build default morphology geometry and AppSpec objects for NEURON sessions."""

    DISPLAY_FIELD_ID = "segment_display"
    HISTORY_FIELD_ID = "segment_history"
    TRACE_FIELD_ID = HISTORY_FIELD_ID

    @staticmethod
    def _ordered_ids(items: dict[str, object], preferred: tuple[str, ...] | None) -> tuple[str, ...]:
        if preferred is None:
            return tuple(items.keys())
        return tuple(item_id for item_id in preferred if item_id in items)

    @staticmethod
    def build_morphology_geometry(sections):
        """Convert NEURON sections with pt3d data into MorphologyGeometrySpec."""

        t0 = time.perf_counter()

        if any(int(sec.n3d()) < 2 for sec in sections):
            from compneurovis.backends.neuron.utils import generate_layout

            generate_layout(sections)

        sec_names = []
        p0s, p1s, d0s, d1s = [], [], [], []
        cums, totals, sec_idx = [], [], []

        for si, sec in enumerate(sections):
            n3d = int(sec.n3d())
            if n3d < 2:
                continue
            sec_names.append(sec.name())
            pts = np.stack([[sec.x3d(i), sec.y3d(i), sec.z3d(i)] for i in range(n3d)], axis=0).astype(np.float32)
            diams = np.array([sec.diam3d(i) for i in range(n3d)], dtype=np.float32)
            diffs = pts[1:] - pts[:-1]
            dlen = np.linalg.norm(diffs, axis=1)
            cum = np.concatenate(([0.0], np.cumsum(dlen)))[:-1]
            total = cum[-1] + dlen[-1] if dlen.sum() > 0 else 1.0

            p0s.append(pts[:-1])
            p1s.append(pts[1:])
            d0s.append(diams[:-1])
            d1s.append(diams[1:])
            cums.append(cum)
            totals.append(np.full_like(dlen, total, dtype=np.float32))
            sec_idx.append(np.full_like(dlen, si, dtype=np.int32))

        p0 = np.vstack(p0s)
        p1 = np.vstack(p1s)
        d0 = np.concatenate(d0s)
        d1 = np.concatenate(d1s)
        cum = np.concatenate(cums)
        total = np.concatenate(totals)
        si = np.concatenate(sec_idx)
        n_segments = p0.shape[0]

        mid = 0.5 * (p0 + p1)
        lengths = np.linalg.norm(p1 - p0, axis=1)
        xloc = (cum + 0.5 * lengths) / total
        radii = 0.5 * (d0 + d1)

        diffs = p1 - p0
        lengths_safe = np.linalg.norm(diffs, axis=1)
        dn = np.zeros_like(diffs)
        nonzero = lengths_safe > 1e-8
        dn[nonzero] = diffs[nonzero] / lengths_safe[nonzero, None]
        cos_t = dn[:, 2]
        ang = np.arccos(np.clip(cos_t, -1.0, 1.0))
        ax = np.cross(np.repeat([[0, 0, 1]], n_segments, axis=0), dn)
        ax_n = np.linalg.norm(ax, axis=1, keepdims=True)
        ax_u = np.zeros_like(ax)
        np.divide(ax, ax_n, out=ax_u, where=(ax_n > 1e-6))
        ux, uy, uz = ax_u.T

        k = np.zeros((n_segments, 3, 3), dtype=np.float32)
        k[:, 0, 1] = -uz
        k[:, 0, 2] = uy
        k[:, 1, 0] = uz
        k[:, 1, 2] = -ux
        k[:, 2, 0] = -uy
        k[:, 2, 1] = ux
        k2 = k @ k
        identity = np.eye(3, dtype=np.float32)[None, :, :]
        orientations = identity + np.sin(ang)[:, None, None] * k + (1.0 - cos_t)[:, None, None] * k2

        entity_ids = tuple(f"{sec_names[idx]}@{float(x):.5f}" for idx, x in zip(si, xloc))
        labels = entity_ids
        section_labels = tuple(sec_names[idx] for idx in si)

        elapsed = time.perf_counter() - t0
        print(f"Meta file generated in {elapsed:.2f}s")

        return MorphologyGeometrySpec(
            id="morphology",
            positions=mid.astype(np.float32),
            orientations=orientations.astype(np.float32),
            radii=radii.astype(np.float32),
            lengths=lengths.astype(np.float32),
            entity_ids=entity_ids,
            section_names=section_labels,
            xlocs=xloc.astype(np.float32),
            labels=labels,
        )

    @staticmethod
    def build_data_app_spec(
        *,
        geometry: MorphologyGeometrySpec,
        display_values: np.ndarray,
        trace_values: np.ndarray,
        trace_segment_ids: np.ndarray,
        trace_times: np.ndarray,
        display_field_id: str | None = None,
        history_field_id: str | None = None,
        display_unit: str | None = None,
        history_unit: str | None = None,
        title: str = "CompNeuroVis",
    ) -> AppSpec:
        """Build a data-only AppSpec (fields + geometry, no views or panels)."""

        display_field_id = display_field_id or NeuronAppSpecBuilder.DISPLAY_FIELD_ID
        history_field_id = history_field_id or NeuronAppSpecBuilder.HISTORY_FIELD_ID
        history_unit = display_unit if history_unit is None else history_unit
        display_field = FieldSpec(
            id=display_field_id,
            initial_values=np.asarray(display_values, dtype=np.float32),
            dims=("segment",),
            coords={"segment": np.asarray(geometry.entity_ids)},
            unit=display_unit,
        )
        trace_field = FieldSpec(
            id=history_field_id,
            initial_values=np.asarray(trace_values, dtype=np.float32),
            dims=("segment", "time"),
            coords={
                "segment": np.asarray(trace_segment_ids),
                "time": np.asarray(trace_times, dtype=np.float32),
            },
            unit=history_unit,
        )
        return AppSpec(
            data=DataCatalog(
                fields={display_field.id: display_field, trace_field.id: trace_field},
                geometries={geometry.id: geometry},
            ),
            view_catalog=ViewCatalog(views={}),
            interactions=InteractionCatalog(controls={}, actions={}),
            layout_catalog=LayoutCatalog.single(LayoutSpec(title=title, panels=(), panel_grid=())),
        )

    @staticmethod
    def build_app_spec(
        *,
        geometry: MorphologyGeometrySpec,
        display_values: np.ndarray,
        trace_values: np.ndarray,
        trace_segment_ids: np.ndarray,
        trace_times: np.ndarray,
        display_field_id: str | None = None,
        history_field_id: str | None = None,
        display_unit: str | None = None,
        history_unit: str | None = None,
        morphology_color_map: str = "scalar",
        morphology_color_limits: tuple[float, float] | None = None,
        morphology_color_norm: str = "auto",
        trace_title: str = "Trace",
        trace_y_label: str = "Value",
        trace_y_unit: str | None = None,
        controls=None,
        actions=None,
        title: str = "CompNeuroVis",
        control_ids: tuple[str, ...] | None = None,
        action_ids: tuple[str, ...] | None = None,
    ) -> AppSpec:
        """Build the default morphology-plus-trace AppSpec for a NEURON backend."""

        display_field_id = display_field_id or NeuronAppSpecBuilder.DISPLAY_FIELD_ID
        history_field_id = history_field_id or NeuronAppSpecBuilder.HISTORY_FIELD_ID
        history_unit = display_unit if history_unit is None else history_unit
        trace_y_unit = (history_unit or "") if trace_y_unit is None else trace_y_unit
        display_field = FieldSpec(
            id=display_field_id,
            initial_values=np.asarray(display_values, dtype=np.float32),
            dims=("segment",),
            coords={
                "segment": np.asarray(geometry.entity_ids),
            },
            unit=display_unit,
        )
        trace_field = FieldSpec(
            id=history_field_id,
            initial_values=np.asarray(trace_values, dtype=np.float32),
            dims=("segment", "time"),
            coords={
                "segment": np.asarray(trace_segment_ids),
                "time": np.asarray(trace_times, dtype=np.float32),
            },
            unit=history_unit,
        )
        views = {
            "morphology": MorphologyViewSpec(
                id="morphology",
                title="Morphology",
                geometry_id=geometry.id,
                color_field_id=display_field.id,
                entity_dim="segment",
                sample_dim=None,
                color_map=morphology_color_map,
                color_limits=morphology_color_limits,
                color_norm=morphology_color_norm,
            ),
            "trace": LinePlotViewSpec(
                id="trace",
                title=trace_title,
                field_id=trace_field.id,
                x_dim="time",
                selectors={"segment": StateBindingSpec("selected_entity_id")},
                x_label="Time",
                y_label=trace_y_label,
                x_unit="ms",
                y_unit=trace_y_unit,
                pen="#1f3c88",
            ),
        }
        controls_dict = {} if controls is None else dict(controls)
        actions_dict = {} if actions is None else dict(actions)
        control_ids = NeuronAppSpecBuilder._ordered_ids(controls_dict, control_ids)
        action_ids = NeuronAppSpecBuilder._ordered_ids(actions_dict, action_ids)
        panels = [
            PanelSpec(
                id="morphology-panel",
                kind=PANEL_KIND_VIEW_3D,
                view_ids=("morphology",),
            ),
            PanelSpec(
                id="trace-panel",
                kind=PANEL_KIND_LINE_PLOT,
                view_ids=("trace",),
            ),
        ]
        panel_grid: list[tuple[str, ...]] = [("morphology-panel", "trace-panel")]
        if control_ids or action_ids:
            panels.append(
                PanelSpec(
                    id="controls-panel",
                    kind=PANEL_KIND_CONTROLS,
                    control_ids=control_ids,
                    action_ids=action_ids,
                )
            )
            panel_grid.append(("controls-panel",))
        return AppSpec(
            data=DataCatalog(
                fields={display_field.id: display_field, trace_field.id: trace_field},
                geometries={geometry.id: geometry},
            ),
            view_catalog=ViewCatalog(views=views),
            interactions=InteractionCatalog(controls=controls_dict, actions=actions_dict),
            layout_catalog=LayoutCatalog.single(
                LayoutSpec(
                    title=title,
                    panels=tuple(panels),
                    panel_grid=tuple(panel_grid),
                )
            ),
        )
