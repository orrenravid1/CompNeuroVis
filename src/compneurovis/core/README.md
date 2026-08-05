---
title: Core Package
summary: Field, geometry, view, control, and scene primitives.
---

# Core Package

`compneurovis.core` defines the stable data and view model:

- `Field`
- `MorphologyGeometry`
- `GridGeometry`
- `OperatorSpec`
- `GridSliceOperatorSpec`
- `Scene`
- `LayoutSpec`
- `PanelSpec`
- `ViewSpec`
- `Network2DViewSpec`
- `ControlSpec`
- `ScalarValueSpec`
- `ChoiceValueSpec`
- `BoolValueSpec`
- `XYValueSpec`
- `ControlPresentationSpec`
- declarative binding helpers such as `AttributeRef` and `SeriesSpec`

`AppSpec` also carries optional `DiagnosticsSpec` settings for app-scoped perf
logging and similar cross-cutting diagnostics.

`LinePlotViewSpec` carries optional presentation hints such as
`rolling_window`, `trim_to_rolling_window`, and `max_refresh_hz`.
`MorphologyViewSpec` and `SurfaceViewSpec` also now support
`max_refresh_hz` as a frontend-owned presentation hint for live 3-D refresh
cadence. These settings shape how the frontend presents updates; they do not
require the backend to hand-tune its emit cadence for each app.

`Network2DViewSpec` describes a fixed directed node/edge graph with live-colored
nodes and edges. It reuses ordinary `Field` instances for node occupancy and
edge flux/rate values instead of introducing a graph-specific data primitive.

`PanelSpec` is the current visible-panel seam. A 3-D `PanelSpec` owns host
concerns such as initial camera distance, turntable orientation, and projected
operator overlays. Those settings belong on the visible panel rather than on
`SurfaceViewSpec` or `MorphologyViewSpec`, which describe rendered content.

Operator specs live alongside fields, geometry, and views so derived workflows
such as grid slices can stay reusable across multiple consumers instead of
being baked into one specific view type.
