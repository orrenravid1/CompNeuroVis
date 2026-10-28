# Proposal: Data-Preserving Fast Surfaces

Status: proposed

## Goal

Make large, changing surfaces fast without decimation, resampling, or changes to
the public authoring API. Every authored coordinate and field value must remain
represented exactly.

The target workload is the animal-sound STFT surface: 513 by 917 samples,
470,421 unique vertices, and 937,984 triangles. The same renderer must continue
to support arbitrary surface fields, height coloring, alpha, display scaling,
axes, and optional shading.

## What the renderer does now

CompNeuroVis already has several useful optimizations:

- `SurfaceRenderer` keeps one `scene.visuals.SurfacePlot` alive while grid shape
  stays fixed.
- `Surface3DVisual` caches field coordinates and rebuilds `meshgrid` arrays only
  when coordinate identity or shape changes.
- A value-only field replacement calls `SurfacePlot.set_data(z=..., colors=...)`
  without resending x/y.
- Axes geometry refresh is routed separately and camera range is not reset on
  every Z update.
- Unlit rendering is the default.
- Explicit `ctx.set_data(surface, values)` updates can avoid surface work
  entirely while snapshot data is unchanged.

These optimizations stop scene reconstruction and transport waste. They do not
produce persistent GPU geometry.

CompNeuroVis currently delegates the mesh to VisPy 0.15.2 `SurfacePlotVisual`,
which delegates drawing to `MeshVisual`. On each changed Z field:

1. CompNeuroVis multiplies full x, y, and z grids by `display_scale`, even when
   x/y and scale are unchanged and even when a scale component is 1.
2. Height coloring normalizes Z on the CPU, creates integer LUT indices, and
   materializes a float32 RGBA array for every unique vertex.
3. `SurfacePlotVisual.set_data` copies Z into an interleaved CPU vertex array and
   invalidates `MeshData` caches.
4. Before drawing, `MeshVisual._update_data` calls
   `MeshData.get_vertices(indexed="faces")`. This expands every indexed triangle
   into three independent vertices.
5. Vertex colors are expanded by faces in the same way. VisPy then replaces the
   vertex and color buffers with those expanded arrays.
6. Lit surfaces additionally recompute and upload face-expanded normals.

Keeping the `SurfacePlot` Python object alive therefore does not keep its GPU
contents stable. The VBO object survives, but its full face-expanded contents
are rebuilt and uploaded after every data change.

## Measured cost

A local CPU microbenchmark reproduced the VisPy array preparation path for the
513 by 917 STFT grid. It excludes GPU driver and rasterization time, so these are
lower-bound costs rather than complete frame timings.

| Item | Current cost |
| --- | ---: |
| Input Z | 1.79 MiB |
| Cached 2-D x/y grids | 3.59 MiB |
| Face table (`uint64` on Windows) | 21.47 MiB |
| Face-expanded positions per update | 32.20 MiB |
| Face-expanded RGBA per update | 42.94 MiB |
| CPU height colormap, median | 16.86 ms |
| `SurfacePlot.set_data`, median | 3.72 ms |
| Face expansion, median | 145.05 ms |

The dominant problem is O(triangle-count) CPU expansion and upload, not field
transport and not the STFT calculation.

## Quick wins on the current renderer

These changes preserve every point and can land before a new visual. They reduce
waste but do not remove VisPy's face-expansion ceiling.

### 1. Cache display-scaled coordinates

Only calculate scaled x/y when coordinates or `display_scale` change. When a
scale component equals 1, reuse the source array instead of multiplying it into
a new array. Apply the same identity shortcut to Z.

Current value-only refreshes allocate scaled x, y, and z arrays before choosing
the Z-only `set_data` branch. Cached x/y remove two needless full-grid
allocations per update.

### 2. Remove redundant initialization work

Surface creation passes x/y/z through the `SurfacePlot` constructor and then
immediately calls full `set_data(x=..., y=..., z=..., colors=...)` again because
`coords_changed` is true.

VisPy 0.15.2 cannot safely receive vertex colors in the constructor because it
sets colors before faces/vertices in its internal `MeshData`. Create geometry
once, then apply only colors on the second call. Uniform-color surfaces need no
second data call.

### 3. Use opaque GL state for opaque surfaces

Current surfaces always select VisPy's `translucent` preset. Select opaque state
when effective alpha is 1 for both uniform and per-vertex color. Return to
translucent state when alpha falls below 1. This keeps the same pixels while
allowing cheaper blending/depth behavior.

### 4. Reuse CPU colormap workspaces

If CPU RGBA mapping remains temporarily, retain normalization, index, and RGBA
arrays per grid shape and use NumPy `out=` operations. This removes several
large temporary allocations and garbage-collection pressure. Cache LUT-plus-
alpha results until colormap or alpha changes.

### 5. Generate `uint32` faces

VisPy's `SurfacePlotVisual` uses `np.uint`, which is `uint64` in the current
Windows environment. A local subclass can override face generation with
`uint32`, sufficient for these vertex counts. This halves face-table memory.

### 6. Extend phase logging

Split `refresh_surface_visual` timing into scene-data, display transform, color
mapping, `set_data`, and draw-preparation phases. Report unique vertices,
triangles, and estimated upload bytes. This lets later work prove which copies
were removed.

The recommended quick-win patch is items 1, 2, 3, and 6. Item 4 is useful if the
new visual is delayed. Item 5 is safe but becomes irrelevant once indexed GPU
drawing replaces `MeshVisual`.

## Main refactor: persistent indexed surface visual

Replace `scene.visuals.SurfacePlot` inside `SurfaceRenderer`; keep the existing
component, refresh-target, field, axes, contribution, and authoring contracts.
No public API change is required.

Create an internal `IndexedSurfaceVisual` with:

- one static float32 XY buffer containing each grid vertex once;
- one static uint32 index buffer containing the two triangles per grid cell;
- one dynamic float32 Z buffer containing each field value once;
- one cached 256-entry RGBA LUT texture;
- a shader that combines XY and Z into position and maps Z through the LUT;
- stable buffer objects updated with `set_subdata` when shape is unchanged.

The same Z buffer can feed both height and color. A 513 by 917 value update then
uploads about 1.79 MiB instead of creating and uploading roughly 75 MiB of
face-expanded position/color data. Triangle count and data fidelity remain
unchanged.

Initial implementation should support the default, high-value path first:

- rectilinear field coordinates;
- unlit surface;
- `color_by="height"` or uniform color;
- color limits, alpha, display scale, and current camera/axes behavior.

Uniform and height-colored paths should share one visual rather than branching
into separate renderer families.

## Height-map texture phase

After indexed buffers establish the performance baseline, add a texture-backed
height path:

- upload the exact float32 Z array as a 2-D texture;
- keep a static grid/index buffer containing one vertex per sample;
- fetch height in the vertex shader;
- use the same height sample for LUT coloring;
- compute smooth normals from neighboring height texels when shading is enabled.

This remains data preserving: texture dimensions equal field dimensions and no
interpolation is used for vertex fetches. Nonuniform x/y coordinates remain in
static one-dimensional coordinate buffers or textures.

A height texture is not automatically faster than a scalar Z vertex buffer for
unlit surfaces; both upload approximately one float per sample. Its main value
is neighbor access for GPU normals and one canonical height source for geometry
and color. Benchmark both paths and retain the simpler indexed-Z path as the
fallback when vertex texture fetch or float texture support is unsuitable.

## Shading

Current VisPy smooth shading asks `MeshData` for face-expanded normals after
vertex changes. That repeats the same CPU expansion problem.

Refactor shading in this order:

1. Ship persistent indexed unlit surfaces.
2. Add flat shading using fragment derivatives where supported.
3. Add smooth normals calculated from neighboring height samples in the height
   shader, respecting x/y spacing.

Until GPU normals exist, lit mode may retain the current renderer as an explicit
temporary fallback. Unlit mode is the default and covers the STFT workload.

## Update rules

Renderer updates should be explicitly separated:

| Change | GPU work |
| --- | --- |
| Z values only | Update Z buffer or height texture |
| Color limits/map/alpha | Update uniforms or 256-entry LUT |
| Display scale | Update uniform only |
| x/y coordinates, same shape | Update static coordinate buffer |
| Grid shape | Rebuild coordinate and index buffers |
| Camera or axes style | No surface-buffer update |

Changing `display_scale` should no longer rewrite every vertex. The shader can
apply it as a uniform.

## Acceptance criteria

- No decimation, resampling, interpolation, or dropped field values.
- Existing surface authoring and `SurfaceRef` remain unchanged.
- Existing grid-slice overlays align exactly with scaled surface coordinates.
- Static coordinate/index buffer identities remain stable across value updates.
- Z-only refresh performs no O(triangle-count) CPU expansion.
- Height colormap runs on GPU for the persistent visual.
- For a 513 by 917 unlit height-colored surface, CPU preparation p95 is below
  8 ms and dynamic upload is at most one float32 value per sample plus small
  uniforms/LUT updates.
- Opaque and translucent output match current behavior.
- Offscreen renderer tests cover initialization, Z-only update, style-only
  update, scale-only update, coordinate update, shape change, cleanup, and
  grid-slice alignment.
- Perf logs demonstrate phase timings and upload estimates before and after.

## Delivery sequence

1. Add quick wins and phase-level measurements to current `SurfaceRenderer`.
2. Add internal persistent indexed visual for unlit surfaces behind the existing
   renderer contract.
3. Switch the default unlit path after visual and performance tests pass.
4. Add height texture and GPU normals.
5. Remove the old `SurfacePlot` path once all supported shading/color modes are
   covered; pre-1.0 code does not need a compatibility layer.

## Non-goals

- Decimation or level-of-detail reduction.
- Changing STFT resolution.
- Changing snapshot transport semantics.
- Adding surface-specific concepts to core specs or model objects.
- Exposing VisPy buffers or shaders through the first-party authoring API.
