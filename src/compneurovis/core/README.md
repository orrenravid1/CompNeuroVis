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
- `ExtensionViewSpec`
- `LevelMarker`
- `ControlSpec`
- `ScalarValueSpec`
- `ChoiceValueSpec`
- `BoolValueSpec`
- `XYValueSpec`
- `ControlPresentationSpec`
- declarative binding helpers such as `AttributeRef` and `SeriesSpec`

`AppSpec` also carries optional `DiagnosticsSpec` settings for app-scoped perf
logging and similar cross-cutting diagnostics.

Core's view layer is deliberately small: `ViewSpec` (the base) and
`ExtensionViewSpec` (the one universal authored view — `kind` + `inputs` +
`properties`), plus the authored `LevelMarker`. **Every** widget, built-in or
third-party, lowers to an `ExtensionViewSpec`. The *typed render-configs* a
frontend rebuilds from it (line/bar plots, surfaces, morphologies, node/edge
graphs) live with that frontend's widget implementations, not in core — core
carries the extension mechanism, not per-widget presentation types. Per-view
hints like `max_refresh_hz` travel in `properties`; they shape how the frontend
presents updates and never require the backend to hand-tune its emit cadence.

`PanelSpec` is the visible-panel seam; it carries only generic panel concerns
(kind, view/control/action/operator ids, host kind, title). View-type-specific
configuration — a 3-D view's initial camera, a surface's axes styling — belongs
to the view (in its `properties`), never bolted onto the generic panel.

Operator specs live alongside fields, geometry, and views so derived workflows
such as grid slices can stay reusable across multiple consumers instead of
being baked into one specific view type.
