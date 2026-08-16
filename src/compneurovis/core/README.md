---
title: Core Package
summary: Field, geometry, view, control, and scene primitives.
---

# Core Package

`compneurovis.core` defines the stable data and view model:

- `Field`
- `FieldSpec`
- `GeometrySpec`
- `OperatorSpec`
- `SelectionSpec`
- `EntityClickSpec`
- `LayoutSpec`
- `PanelSpec`
- `ViewSpec`
- `ControlSpec`
- `ControlValueSpec`
- `ControlPresentationSpec`
- declarative binding helpers such as `AttributeRef` and `SeriesSpec`

`AppSpec` also carries optional `DiagnosticsSpec` settings for app-scoped perf
logging and similar cross-cutting diagnostics.

Core's canonical presentation boundary is deliberately small: kind-keyed
`GeometrySpec`, `OperatorSpec`, and `ViewSpec`, plus neutral `SelectionSpec` state
and `EntityClickSpec` commands. Widget packages own typed authoring declarations and frontend
render configs; canonical `AppSpec` carries only these language-neutral specs.
Every widget, built-in or third-party, lowers to a `ViewSpec` containing its
`kind`, inputs, geometry and selection references, properties, and host choice.
Typed render configs such as line, surface, or morphology configs live with the
frontend implementations that consume them. Per-view hints such as
`max_refresh_hz` shape presentation without requiring a backend to tune its emit
cadence.

`SelectionSpec` gives geometry-scoped state, initial value, and single/multiple
policy; it does not imply clicking or highlighting. `EntityClickSpec` separately
names a geometry click and may opt into default selection behavior by linking one
selection. A view separately names click roles and selection state it consumes, so
renderers may highlight, filter, label, or otherwise present selection without a
core visual policy.

`PanelSpec` is the visible-panel seam; it carries only generic panel concerns
(kind, view/control/action/operator ids, host kind, title). View-type-specific
configuration — a 3-D view's initial camera, a surface's axes styling — belongs
to the view (in its `properties`), never bolted onto the generic panel.

Operator specs live alongside fields, geometry, and views so derived workflows
such as grid slices can stay reusable across multiple consumers instead of
being baked into one specific view type. `OperatorSpec` names both its
data inputs and geometry dependencies through scoped refs; its output remains an
ordinary data source that any view may consume.
