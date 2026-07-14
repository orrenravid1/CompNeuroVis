# Source Organization Review

Scope: systematic `audit-source-organization` review of core platform files,
session/transport files, builders, backend-specific code, VisPy frontend code,
and support utilities. This is a maintainability/read-order review, not a
behavior correctness review.

## Executive Summary

The repository has a clear conceptual architecture, but several implementation
files no longer read in the same order as the architecture. The worst pattern is
not bad names. It is accumulated responsibility: large files and methods now
hide distinct subsystems that deserve names and boundaries.

Highest-impact hotspots:

1. `src/compneurovis/frontends/vispy/frontend.py`
   - `VispyFrontendWindow` is 1,194 lines.
   - `_poll_transport` is 184 lines and embeds the protocol reducer inside a Qt
     timer callback.
   - Refresh cadence logic is duplicated for line plots, state graphs, and 3-D
     views.
   - Planner and window duplicate scene navigation such as "which operators
     belong to this view."

2. `src/compneurovis/core/scene.py`
   - `Scene` appears only at line 277 because `LayoutSpec` and panel
     normalization dominate the file.
   - `_normalize_explicit_panels` is 122 lines and mixes classification,
     validation, deduplication, defaulting, and `PanelSpec` reconstruction.
   - View-to-panel classification is duplicated between explicit normalization
     and default panel derivation.

4. `src/compneurovis/session/pipe.py`
   - `_session_process` and `_session_process_queue` duplicate the worker loop
     with transport-specific I/O interleaved into session lifecycle logic.
   - `PipeTransport.__init__` mixes validation, mode selection, process/thread
     setup, queue/pipe setup, and fallback construction.

5. Backend morphology-trace scaffolding
   - `backends/neuron/session.py` and `backends/jaxley/session.py` each exceed
     500 lines and duplicate interaction context, action policy, trace history,
     display-field updates, click/key handling, and field max-sample logic.
   - `backends/neuron/scene.py` and `backends/jaxley/scene.py` duplicate the
     default morphology-plus-trace `build_scene` almost line-for-line.

## Refactor Progress

- 2026-04-27: Split `src/compneurovis/frontends/vispy/renderers.py` into the
  `renderers/` package with `colormaps.py`, `morphology.py`, `surface.py`, and
  overlay modules. The package root no longer re-exports renderer classes.
- 2026-04-27: Split overlay implementation into `axes_overlay.py` and
  `slice_overlay.py`. Extracted overlay geometry construction from VisPy visual
  mutation.
- 2026-04-27: Extracted `frontends/vispy/view_inputs/` from `panels.py` for
  state binding, surface scene extraction, and grid-slice projection adapters.
- 2026-04-27: Refactored `LinePlotPanel.refresh` and
  `ControlsPanel._build_control_row` into smaller phase/widget helpers.
- 2026-04-27: Extracted the 3-D canvas host into generic `view3d/viewport.py` and
  moved concrete morphology/surface behavior into mounted visual adapters in
  `view3d/visuals.py`. `Viewport3DPanel` no longer constructs, stores, or
  refreshes content-specific renderers.
- 2026-04-27: Converted `frontends/vispy/panels.py` into the `panels/` package:
  `view3d.py`, `line_plot.py`, `state_graph.py`, and `controls.py`. The package
  root no longer re-exports panel classes; imports now target the owning module.
- 2026-04-27: Moved simulator utility roots under their owning backend packages:
  `backends/neuron/utils/` and `backends/jaxley/utils/`. Moved the VisPy-only
  capped-cylinder primitive under `frontends/vispy/utils/`. Removed the old
  top-level `neuronutils`, `jaxleyutils`, and `vispyutils` roots.

## Score Table

Scores use the `audit-source-organization` 0-16 rubric.

| Area | File or class | Score | Verdict |
|---|---|---:|---|
| Core | `core/scene.py` | 6 | Hard to maintain |
| Core | `session/pipe.py` | 7 | Hard to maintain |
| Core | `core/field.py` | 10 | Acceptable but drifting |
| Core | `session/protocol.py` | 14 | Good |
| Core | `core/geometry.py` | 14 | Good |
| Core | `core/views.py` | 14 | Good |
| Frontend | `frontend.py` overall | 8 | Hard to maintain |
| Frontend | `frontend.py` transport update reduction | 5 | Actively obscuring |
| Frontend | `frontend.py` refresh scheduling | 6 | Hard to maintain |
| Frontend | `panels/` package | 14 | Good |
| Frontend | `view_inputs/` package | 15 | Good |
| Frontend | `view3d/viewport.py` | 15 | Good |
| Frontend | `view3d/visuals.py` | 13 | Acceptable |
| Frontend | `LinePlotPanel` | 12 | Acceptable |
| Frontend | `StateGraphPanel` | 8 | Hard to maintain |
| Frontend | `ControlsPanel` | 12 | Acceptable |
| Frontend | `renderers/` package | 14 | Good |
| Frontend | `SurfaceAxesOverlay` | 12 | Acceptable |
| Frontend | `MorphologyRenderer` | 12 | Acceptable |
| Backend | `backends/neuron/session.py` | 8 | Hard to maintain |
| Backend | `backends/jaxley/session.py` | 7 | Hard to maintain |
| Backend | `backends/neuron/scene.py` | 9 | Hard to maintain |
| Backend | `backends/jaxley/scene.py` | 8 | Hard to maintain |
| Builders | `builders/surface.py` | 10 | Acceptable but drifting |
| Builders | `builders/replay.py` | 14 | Good |
| Utilities | `frontends/vispy/utils/cappedcylindercollection.py` | 8 | Hard to maintain |
| Utilities | `backends/neuron/utils/json_utils.py` | 7 | Hard to maintain |
| Utilities | `backends/jaxley/utils/swc_utils.py` | 10 | Acceptable but drifting |
| Scripts | `scripts/pr_readiness.py` | 11 | Acceptable but drifting |

## Platform Findings

### `core/scene.py`

Problem: the file is called `scene.py`, but `Scene` is buried after layout and
panel normalization. A reader must understand layout policy before reaching the
central container type.

Findings:

- `LayoutSpec` starts at `core/scene.py:36` and dominates the file.
- `Scene` starts at `core/scene.py:277`.
- `_normalize_explicit_panels` starts at `core/scene.py:105` and is 122 lines.
- Panel kind branches at lines 123, 151, 178, and 193 repeat the same pattern.
- `_derive_default_panels` at line 228 duplicates view-to-panel classification.

Recommended boundary:

- Extract `PanelSpec`, panel constants, and `LayoutSpec` into `core/layout.py`.
- Leave `scene.py` to introduce `Scene`, `AppSpec`, and `DiagnosticsSpec`.
- Add one `_panel_kind_for_view(view)` helper or equivalent policy boundary.
- Split normalization into per-kind helpers.

### `session/pipe.py`

Problem: transport mechanics and worker lifecycle are interleaved. The pipe and
thread worker loops are near duplicates.

Findings:

- `_session_process` starts at `session/pipe.py:56`.
- `_session_process_queue` starts at `session/pipe.py:125`.
- Both loops repeat command drain, stop handling, `advance`, `read_updates`,
  perf logging, sleep cadence, error handling, and shutdown.
- `PipeTransport.__init__` starts at line 204 and mixes mode selection and
  construction details.

Recommended boundary:

- Extract one `_session_worker_loop(adapter, session_source, diagnostics)`.
- Give adapters `recv_commands`, `send_update`, and `should_stop` operations.
- Split `PipeTransport.__init__` into `_init_pipe_mode` and `_init_thread_mode`.

### `core/field.py`

Problem: generally readable, but selector behavior is getting dense.

Findings:

- `resolve_indexer` starts at `core/field.py:135` and hides the full selector
  language behind one small-sounding name.
- `append`, `resolve_indexer`, and `select` together form a compact query/update
  engine inside the dataclass.

Recommended boundary:

- Extract `_resolve_array_selector`, `_resolve_label_selector`, and
  `_resolve_numeric_selector` before more selector behavior is added.

## Frontend Findings

### `frontend.py`

Problem: `VispyFrontendWindow` is a frontend subsystem, not just a window class.
It owns app startup, scene indexing, layout building, refresh planning,
refresh execution, dirty queues, transport update reduction, controls/actions,
keyboard dispatch, interaction target adapters, and public accessors.

Findings:

- `VispyFrontendWindow` starts at `frontend.py:364` and spans 1,194 lines.
- `_poll_transport` starts at `frontend.py:1233` and is 184 lines.
- Refresh cadence is repeated in:
  - `_refresh_state_graph_if_due` at `frontend.py:948`
  - `_refresh_line_plot_if_due` at `frontend.py:1030`
  - `_refresh_view_3d_if_due` at `frontend.py:1074`
- Scene navigation is duplicated between planner and window:
  - `_view_ids_in_3d_panels` at `frontend.py:172` and `frontend.py:508`
  - grid-slice operator ownership at `frontend.py:199` and `frontend.py:811`
- `_make_panel_for_cell` at `frontend.py:613` is a 71-line panel factory.
- Refresh target classification is spread across string constants, classmethods,
  `VIEW_3D_TARGET_KINDS`, a hard-coded ordering dict, and filters.

Recommended boundaries:

- `presentation_index.py`: central scene/panel/view/operator lookup.
- `refresh_scheduler.py`: dirty sets, last-refresh times, intervals, fairness,
  max-per-flush limits.
- `update_reducer.py`: apply `SessionUpdate`s to scene/state and return refresh
  targets, status, and perf counters.
- `panel_factory.py`: panel-kind dispatch and host construction.
- Keep `frontend.py` as Qt window lifecycle plus wiring.

### `panels/` Package

Status: split into focused panel modules. The old broad module was converted
into a package; panel imports now target the owning module.

Findings:

- `panels/line_plot.py` is 553 lines and centered on line plotting.
- `LinePlotPanel.refresh` at `panels/line_plot.py:101` is 23 lines and reads as a mode
  dispatcher.
- `LinePlotPanel._refresh_series` is 10 lines; its former phases now live in
  `_series_plot_data`, `_apply_series_structure`, `_update_series_items`, and
  `_update_series_legend`.
- `StateGraphPanel.refresh` now appears in `panels/state_graph.py`, but
  `_build_visuals` remains a 88-line implementation hotspot.
- `ControlsPanel._build_control_row` in `panels/controls.py` is 18 lines and
  dispatches to `_add_float_control`, `_add_int_control`, `_add_bool_control`,
  and `_add_choice_control`.
- State-graph helper functions now live beside `StateGraphPanel` instead of
  sitting between unrelated panel classes.
- Grid-slice projection helpers now live in `view_inputs/grid_slice.py` instead of being
  buried after the controls implementation.

Recommended boundaries:

- `panels/line_plot.py`
- `panels/state_graph.py`
- `panels/controls.py`
- `panels/view3d.py`
- `view3d/viewport.py`
- `view3d/visuals.py`
- Keep `view_inputs/` split by adapter concept: `bindings.py`, `surface.py`,
  and `grid_slice.py`.

### `renderers/` package

Status: first refactor slices completed. The old single file is now a package,
so the names-only module order exposes the renderer concepts directly:
`colormaps.py`, `morphology.py`, `surface.py`, `axes_overlay.py`, and
`slice_overlay.py`.

Findings:

- `renderers/__init__.py` is only a package marker.
- `renderers/colormaps.py` is a leaf helper module.
- `renderers/morphology.py` now starts directly with `MorphologyRenderer`.
- `renderers/surface.py` now starts directly with `SurfaceRenderer`.
- `renderers/axes_overlay.py` now starts directly with `SurfaceAxesOverlay`.
- `SurfaceAxesOverlay.set_axes_geometry` is 30 lines, with pure geometry
  construction below the class.
- `renderers/slice_overlay.py` now starts directly with `SurfaceSliceOverlay`.
- `SurfaceSliceOverlay.set_slice` is 7 lines.
- `SurfaceRenderer.update_surface` and `update_surface_style` now share
  `_surface_appearance` for style, shading, and color resolution.

Remaining boundaries:

- `SurfaceRenderer.update_surface` is still a dense VisPy upload path, but it is
  now one responsibility: create or update the surface visual.

## Backend And Builder Findings

### NEURON/Jaxley sessions

Problem: backend-specific files duplicate a shared morphology-display/session
workflow. The simulator-specific parts are harder to see because the common
trace/action/interaction machinery is repeated inside each backend.

Findings:

- `NeuronSession` starts at `backends/neuron/session.py:51` and spans 524 lines.
- `JaxleySession` starts at `backends/jaxley/session.py:54` and spans 529 lines.
- `SessionInteractionContext` is duplicated in both files.
- Trace selection/history, display field replacement, max sample resolution,
  action dispatch, entity click handling, and reset handling are duplicated.
- `JaxleySession.initialize` at `backends/jaxley/session.py:245` is 59 lines
  and phase-heavy.
- `NeuronSession.initialize` at `backends/neuron/session.py:252` is shorter but
  still mixes simulator setup, geometry, recorder setup, sampling, trace setup,
  scene creation, max-sample derivation, and UI state emission.

Recommended boundaries:

- `TraceHistory` helper for selected/full trace capture.
- Shared interaction context or command handler.
- Shared default action policy.
- Backend files should read as: build simulator, initialize runtime, sample,
  emit backend-specific updates.

### NEURON/Jaxley scene builders

Problem: default morphology-trace scene assembly is duplicated almost
line-for-line.

Findings:

- `NeuronSceneBuilder.build_scene` starts at `backends/neuron/scene.py:117` and
  is 112 lines.
- `JaxleySceneBuilder.build_scene` starts at `backends/jaxley/scene.py:169` and
  is 112 lines.
- Both mix field construction, view construction, control/action ordering,
  panel construction, and layout construction.
- `build_morphology_geometry` in both backends is a long geometry algorithm plus
  object construction.

Recommended boundaries:

- Shared `build_morphology_trace_scene(...)` helper parameterized by backend
  ids/defaults.
- Shared orientation-from-direction geometry math.

### Builders

Problem: most builders are readable, but surface assembly is drifting.

Findings:

- `builders/surface.py:54` `build_surface_app` is 109 lines and mixes default
  view creation, operator discovery, user panel patching, panel construction,
  grid derivation, and scene assembly.
- `builders/replay.py` reads well.
- `builders/neuron.py` and `builders/jaxley.py` are clean.

Recommended boundary:

- Extract `_default_grid_slice_operator_ids`, `_resolve_surface_panels`, and
  `_derive_panel_grid`.

## Utility Findings

### `frontends/vispy/utils/cappedcylindercollection.py`

Problem: the outline hides most of the actual phases.

Findings:

- `CappedCylinderCollection.__init__` starts at line 19 and is 108 lines.
- It mixes validation, shared mesh construction, transform math, cache
  initialization, and VisPy node creation.

Recommended boundary:

- Extract `_side_geometry`, `_cap_geometry`, `_side_transforms`, and
  `_cap_instance_data`.

### `backends/neuron/utils/json_utils.py`

Problem: public function names are clear, but each hides many serialization
phases.

Findings:

- `export_section_json` starts at line 4 and is 95 lines.
- `import_section_json` starts at line 100 and is 81 lines.
- They mix topology, geometry, mechanisms, ions, point processes, JSON assembly,
  file I/O, and printing.

Recommended boundary:

- Separate extraction/serialization from file I/O.
- Add helpers for mechanisms, ions, point processes, and geometry.

### `backends/jaxley/utils/swc_utils.py`

Problem: mostly coherent, but live loading and cache building duplicate graph
navigation.

Findings:

- `_build_cells_from_swc` and `_build_cache_payload` duplicate root discovery,
  basename/root naming, graph construction, compartment graph construction, and
  per-root iteration.

Recommended boundary:

- Shared `_iter_root_compartment_graphs(...)` helper.

## Recommended Refactor Sequence

Use small, behavior-preserving PRs. Do not start by moving everything.

1. Frontend extraction phase 1: `frontend.py` update reducer
   - Extract `TransportUpdateReducer` or equivalent from `_poll_transport`.
   - Keep behavior identical.
   - Add targeted tests around update reduction if possible.

2. Frontend extraction phase 2: scene presentation index and refresh scheduler
   - Extract shared scene/panel/operator lookup.
   - Then extract repeated refresh cadence logic.
   - This reduces duplication before splitting panel files.

3. Core layout extraction
   - Move `PanelSpec`, constants, and `LayoutSpec` to `core/layout.py`.
   - Split panel normalization by kind.
   - Preserve public exports from `compneurovis.core` and top-level
     `compneurovis`.

4. Backend shared morphology-trace scaffolding
   - Extract shared trace history and default scene builder.
   - Do this after core layout is stable to avoid duplicate churn in builders.

5. Frontend panel/render module split
   - Completed the first split: `panels/`, `view3d/`, and `renderers/` now
     mirror one another as focused subsystem packages.
   - Next cleanup is inside `panels/state_graph.py` and `panels/controls.py`,
     not a package-boundary problem.

6. Transport worker loop cleanup
   - Extract a single worker loop with pipe/thread adapters.
   - Consider separating Qt `QObject` transport adapter from session transport
     core as a follow-up architectural cleanup.

7. Utility cleanup
   - Refactor `CappedCylinderCollection.__init__`.
   - Refactor `backends/neuron/utils/json_utils` into extraction/assembly/I/O
     helpers.

## External Baseline: VisPy And Matplotlib

Local comparison used installed packages:

- VisPy `0.15.2`
- Matplotlib `3.10.8`

Official repository context:

- VisPy describes its structure around explicit subpackages: `app`, `gloo`,
  `scene`, visuals, transforms, shaders, scene graph, and `plot`.
- Matplotlib is much larger and older; its repository is a broad plotting
  platform with GUI backends, figures, axes, artists, transforms, colors, tests,
  and C/C++ extension code.
- Matplotlib has historical precedent for splitting a large module without
  changing public API: the old `axes.py` was split into an `axes` package with
  private submodules such as `_base.py`, `_axes.py`, and `_subplots.py`.

Measured source-size comparison:

| Project | Representative file | Lines | Longest function/method | Notes |
|---|---:|---:|---:|---|
| CompNeuroVis | `frontends/vispy/frontend.py` | 1,648 | 184 | Window, update reducer, refresh scheduler, panel factory, and interaction adapter in one file. |
| CompNeuroVis | `frontends/vispy/panels/line_plot.py` | 553 | 32 | One panel family; phases are named and public refresh is near the top. |
| CompNeuroVis | `frontends/vispy/panels/state_graph.py` | 284 | 88 | One panel family; `_build_visuals` remains the next local hotspot. |
| CompNeuroVis | `frontends/vispy/panels/controls.py` | 496 | 54 | One panel family plus XY pad; widget-family builders are separated. |
| CompNeuroVis | `frontends/vispy/renderers/` | 914 total | 62 | Split into renderer-specific modules; public overlay methods now delegate to named geometry helpers. |
| VisPy | `app/canvas.py` | 828 | 103 | App/canvas subsystem; comparable to our frontend window but about half the size. |
| VisPy | `visuals/image.py` | 701 | 64 | One primary visual concept. |
| VisPy | `visuals/markers.py` | 819 | 84 | One primary visual concept. |
| VisPy | `visuals/volume.py` | 1,366 | 82 | Large, but still centered on one visual. |
| VisPy | `color/colormap.py` | 1,213 | 64 | Large but cohesive color subsystem. |
| Matplotlib | `axes/_axes.py` | 8,871 | 504 | Huge public plotting API surface; not a model for a young internal module. |
| Matplotlib | `axes/_base.py` | 4,857 | 167 | Shared Axes base machinery. |
| Matplotlib | `pyplot.py` | 4,644 | 200 | Compatibility/procedural API wrapper layer. |

Interpretation:

- VisPy is the closer quality bar for this project. Its files can be large, but
  they usually center on one primary concept: one visual, one app/canvas layer,
  one color subsystem, one event subsystem.
- Matplotlib proves large files can survive with enough history, tests, and API
  discipline, but it also proves that large modules eventually need internal
  splitting. Its scale should not be used to justify keeping young internal
  code monolithic.
- CompNeuroVis is already clean in the small core primitives (`views.py`,
  `controls.py`, `geometry.py`, `protocol.py`). The weaker files are weaker not
  because they are larger than Matplotlib, but because they are large while
  mixing multiple private subsystems that are still easy to separate.

Practical bar:

- Prefer the VisPy style: one dominant concept per module, private helpers close
  to that concept, and explicit subsystem packages once a file starts carrying
  multiple concepts.
- Treat Matplotlib-style large files as acceptable only for mature public APIs,
  not internal orchestration code.
- For CompNeuroVis, a 700-1,200 line file may be acceptable only when it has one
  obvious owner concept. The renderer package is now closer to that bar;
  `frontend.py` still crosses the line because it contains several owner
  concepts.

## Files That Are Already In Good Shape

- `core/views.py`
- `core/controls.py`
- `core/geometry.py`
- `core/bindings.py`
- `core/operators.py`
- `core/state.py`
- `session/protocol.py`
- `session/base.py`
- `builders/neuron.py`
- `builders/jaxley.py`
- `builders/replay.py`
- most generated-index and metadata check scripts

These should be used as style anchors: short files, predictable ordering, and
names-only outlines that match the package mental model.
