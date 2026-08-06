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

The alpha frontend has three deliberate panel-host families:

- `extension`: any standalone QWidget, including 2-D plots, tables, images,
  text, dashboards, and custom UI;
- `view_3d`: a visual inside the shared Vispy canvas/camera/picking lifecycle;
- `controls`: framework-generated typed controls.

Widget kinds inside those families are open. A new panel-host family changes
frontend shell/lifecycle behavior and is not an ordinary widget plugin.
`view_3d` currently supports the `independent_canvas` host lifecycle. A widget
registers a visual inside that lifecycle; a new canvas-ownership strategy needs a
frontend-shell extension.

App-local widgets call
`register_vispy_plugin("module:register")`; the renderer module is imported only
by the frontend. Installed distributions expose the same callback via
`compneurovis.vispy_plugins`. Inside it, authors use `register_renderer`,
`register_3d_visual`, and `register_operator_adapter`. Ordinary extension hosts
refresh as a unit. A 3-D registration owns its typed-config builder and surgical
refresh routing in the same call.

`renderers/` contains the VisPy-facing renderer classes, surface overlay
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

3-D presentation cadence is now frontend-owned as well. Morphology and surface
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
grid-slice projections stay inside the surface adapter. New 3-D visual families
should add another adapter that fits this contract, not another field or method
on `Viewport3DPanel`.

Grid slicing lowers to `ExtensionOperatorSpec(kind="grid_slice")`. Its
kind-registered adapter renders a host-level overlay and also supplies ordinary
data to consumers such as a line plot, without turning the operator into
implicit surface-view state.

Third-party operator adapters use the public
`compneurovis.frontends.vispy.register_operator_adapter` surface.
`OperatorResolveContext` provides scoped field/geometry lookup plus current values, and
`RefreshTarget` lets an adapter route changes to registered 3-D targets or the ordinary
extension-host baseline. Package code owns kind-specific interpretation; the frontend
planner and output resolver dispatch only by the neutral operator `kind`.

3D layout is now routed through explicit panel specs:

- `PanelSpec(kind="view_3d")` describes how one or more 3D views are mounted
- Starting camera (distance, azimuth, elevation) is a property of the 3-D *view*,
  not the panel — the host reads it off the primary view's render-config and hands
  it to `Viewport3DPanel`
- `PanelSpec.operator_ids` selects which operator overlays the host should project
- `IndependentCanvas3DHostPanel` is the current built-in host implementation

That keeps the current one-view-one-canvas behavior intact while leaving room for future shared-canvas or shared-scene hosts.

The Network2D widget renders static directed node/edge graphs with live-colored
nodes and edges. `Network2DPanel` draws node values and edge flux/rate values
using a VisPy `SceneCanvas` with `PanZoomCamera`, and follows the same throttled
refresh cadence as line plots. `Network2DViewSpec` keeps the graph layout on the
view while `node_field_id` and `edge_field_id` point at ordinary `Field` objects.
`Network2DViewSpec.max_refresh_hz` is the per-view override seam.
