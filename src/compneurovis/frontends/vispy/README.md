---
title: VisPy Frontend Package
summary: Current PyQt6/VisPy frontend panels, renderers, and window orchestration.
---

# VisPy Frontend Package

This package contains the current runnable frontend:

- `renderers/`
- `view3d/`
- `panels/`
- `view_inputs/`
- `utils/`
- `frontend.py`

The built-in distribution registers three current panel hosts:

- `extension`: any standalone QWidget, including 2-D plots, tables, images,
  text, dashboards, and custom UI;
- `scene_3d`: layers inside the shared Vispy canvas/camera/picking lifecycle;
- `controls`: framework-generated typed controls.

That list is not closed. `register_panel_host(kind, factory)` adds a complete
panel lifecycle from the same deferred plugin callback used for renderers. The
returned lifecycle owns construction, refresh-target claiming and cadence,
visibility, sizing intent, inspection capabilities, and disposal. The frontend
window contains no panel-kind dispatch. Use a new panel kind only when a widget
actually needs a different host lifecycle; arbitrary standalone QWidgets should
continue to use `extension`.

`scene_3d` is an ordinary registered shared-canvas host, not a privileged view
type. A 3-D QWidget that does not need shared-scene composition remains an
ordinary `extension` host.

App-local widgets call
`register_vispy_plugin("module:register")`; the renderer module is imported only
by the frontend. Installed distributions expose the same callback via
`compneurovis.vispy_plugins`. Inside it, authors use `register_renderer`,
`register_panel_host`, `register_scene_layer`, and `register_operator_adapter`.
Ordinary extension hosts refresh as a unit. A 3-D registration owns its
typed-config builder and surgical refresh routing in the same call.

`renderers/` contains the VisPy-facing renderer classes
visuals, and shared colormap sampling helpers. Import renderer classes from the
specific module that owns them.
`view3d/` contains the generic VisPy canvas/camera host plus built-in 3-D
visual adapters. The viewport mounts and activates 3-D visual objects, but it
does not know which visual families exist.
`panels/` contains the visible Qt panel families: 3-D hosts, line plots, state
graphs, and controls. Import panel classes from the specific module that owns
them.
`view_inputs/` contains adapters from core `Field`, `OperatorSpec`, and
frontend state objects into concrete panel or visual inputs. It is split into
state-binding resolution, surface scene preparation, and grid-slice projection.
`utils/` contains VisPy-only low-level visual primitives that are not generic
core utilities.

The frontend uses explicit refresh targets and long-lived renderer objects so state changes can update only the affected layers instead of forcing a full scene rebuild. Surface-axis overlays now split geometry refresh from style refresh and reuse pooled line/text visuals instead of rebuilding every tick label on each control drag.

Surface and morphology renderers share one scalar-colormap sampler. Built-in
strings such as `scalar`, `bwr`, `fire`, and `grayscale` still work, custom
ramps can use `ramp:<high>` or `ramp:<low>:<high>`, and optional matplotlib
sampling is available through `mpl:<name>` and `mpl-ramp:<low>:<high>` when
the `matplotlib` extra is installed.

Line-plot panels support both single-trace views and multi-series fields, and the window can mount multiple line-plot views at once while still collapsing cleanly to a 2D-first layout when a scene has no 3D view. Like 3-D views, each line plot now sits inside a small host wrapper so framed chrome and titles stay consistent across panel types. The controls region now uses the same host-wrapper pattern, too, so the whole window presents one consistent panel language.

Line-plot presentation cadence is now frontend-owned. Incoming line-plot
targets mark a plot dirty, and the frontend redraws that plot on a capped
schedule by default instead of assuming every append or state change must force
an immediate pyqtgraph refresh. `LinePlotViewSpec.max_refresh_hz` is the
per-view override seam; values `<= 0` opt out of throttling.
The plot widget itself also enables pyqtgraph clip-to-view and auto
downsampling defaults so redraw cost tracks the visible viewport more closely
when users maximize the window or keep several live traces open.

3-D presentation cadence is owned by the registered 3-D panel lifecycle.
Morphology and surface
refresh targets mark the affected 3-D view dirty, and the frontend presents
those updates on a capped schedule by default instead of repainting the canvas
on every live field update. `MorphologyViewSpec.max_refresh_hz` and
`SurfaceViewSpec.max_refresh_hz` are the per-view override seams; values
`<= 0` opt out of throttling. Both the 3-D and line-plot paths also budget how
many dirty views they present in one flush so one busy live panel does not
starve the rest of the window.

`Viewport3DPanel` is intentionally generic. It owns the canvas, camera, active
visual key, commit path, and generic click dispatch. Concrete content lives in
mounted visual adapters such as `Morphology3DVisual` and `Surface3DVisual`.
The current independent-canvas host mounts only the adapter claimed by its
primary view kind; renderer-owned details such as surface axes and
intrinsic surface axes stay inside the surface adapter. Grid-slice projections
are independent visual contributions owned by GridSlice. New 3-D visual families
should add another adapter that fits this contract, not another field or method
on `Viewport3DPanel`.

Grid slicing lowers to `ExtensionOperatorSpec(kind="grid_slice")` for data
and a separate `VisualContributionSpec(kind="grid_slice_overlay")` for scene
graphics. The operator adapter supplies ordinary data to consumers such as a
line plot; the contribution renderer owns the host-level overlay.

Third-party operator adapters use the public
`compneurovis.frontends.vispy.register_operator_adapter` surface.
`OperatorResolveContext` provides scoped field/geometry lookup plus current values, and
`RefreshTarget` lets an adapter route changes to registered 3-D targets or the ordinary
extension-host baseline. Package code owns kind-specific interpretation; the frontend
planner and output resolver dispatch only by the neutral operator `kind`.

3D layout is now routed through explicit panel specs:

- `PanelSpec(kind="scene_3d")` selects the registered shared-scene host
- Starting camera (distance, azimuth, elevation) is a property of the 3-D *view*,
  not the panel — the host reads it off the primary view's render-config and hands
  it to `Viewport3DPanel`
- `PanelSpec.contribution_ids` selects independent visuals mounted through the
  host's advertised capability
- `IndependentCanvas3DHostPanel` is the current built-in host implementation

That keeps the current one-view-one-canvas behavior intact while leaving room for future shared-canvas or shared-scene hosts.

The Network2D widget renders static directed node/edge graphs with live-colored
nodes and edges. `Network2DPanel` draws node values and edge flux/rate values
using a VisPy `SceneCanvas` with `PanZoomCamera`, and follows the same throttled
refresh cadence as line plots. `Network2DViewSpec` keeps the graph layout on the
view while `node_field_id` and `edge_field_id` point at ordinary `Field` objects.
`Network2DViewSpec.max_refresh_hz` is the per-view override seam.
