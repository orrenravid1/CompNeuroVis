---
title: Core Package
summary: Field, geometry, view, control, and scene primitives.
---

# Core Package

`compneurovis.core` defines the stable data and view model:

- `Field`
- `FieldSpec`
- `GeometrySpec`
- `ExtensionGeometrySpec`
- `MorphologyGeometrySpec`
- `OperatorSpec`
- `ExtensionOperatorSpec`
- `SelectionSpec`
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

Core's extension layer is deliberately small: kind-keyed
`ExtensionGeometrySpec`, `ExtensionOperatorSpec`, and `ExtensionViewSpec`, plus
neutral `SelectionSpec` interaction state.
Widget packages own typed declarations and frontend render configs; canonical
`AppSpec` carries only these language-neutral envelopes. The view layer has
`ViewSpec` (the base) and
`ExtensionViewSpec` (the one universal authored view — `kind` + `inputs` +
`geometries` + `selections` + `properties`), plus the authored `LevelMarker`. **Every** widget, built-in or
third-party, lowers to an `ExtensionViewSpec`. The *typed render-configs* a
frontend rebuilds from it (line/bar plots, surfaces, morphologies, node/edge
graphs) live with that frontend's widget implementations, not in core — core
carries the extension mechanism, not per-widget presentation types. Per-view
hints like `max_refresh_hz` travel in `properties`; they shape how the frontend
presents updates and never require the backend to hand-tune its emit cadence.

`SelectionSpec` gives selectable geometry fragment-scoped state, initial value, and
single/multiple policy. A view explicitly names the selections it owns, so a picking event
routes by selection identity rather than process-wide selected-entity keys.

`PanelSpec` is the visible-panel seam; it carries only generic panel concerns
(kind, view/control/action/operator ids, host kind, title). View-type-specific
configuration — a 3-D view's initial camera, a surface's axes styling — belongs
to the view (in its `properties`), never bolted onto the generic panel.

Operator specs live alongside fields, geometry, and views so derived workflows
such as grid slices can stay reusable across multiple consumers instead of
being baked into one specific view type. `ExtensionOperatorSpec` names both its
data inputs and geometry dependencies through scoped refs; its output remains an
ordinary data source that any view may consume.
