"""Raw VisPy sphere rendering matrix.

This deliberately imports no CompNeuroVis code.  Each panel exercises a
different sphere/mesh material path while keeping the camera and scene setup
identical.

Run with::

    poetry run python scratch/vispy_spheres.py
"""

from __future__ import annotations

from vispy import app, scene
from vispy.geometry import create_sphere


CASES = (
    "Latitude sphere: unlit",
    "Icosphere: unlit",
    "Cube sphere: unlit",
    "Latitude sphere: smooth",
    "Direct mesh: unlit",
    "Icosphere: alpha blend + back culling",
)


def _add_reference_geometry(view) -> None:
    # Gives every panel visible depth/scale references even if its sphere fails.
    scene.visuals.XYZAxis(parent=view.scene)
    scene.visuals.Line(
        pos=(
            (-1.4, -1.4, -1.1),
            (1.4, -1.4, -1.1),
            (1.4, 1.4, -1.1),
            (-1.4, 1.4, -1.1),
            (-1.4, -1.4, -1.1),
        ),
        color=(0.65, 0.65, 0.65, 1.0),
        width=1.0,
        parent=view.scene,
    )


def _configure_view(view) -> None:
    view.bgcolor = (0.06, 0.07, 0.09, 1.0)
    view.camera = scene.cameras.TurntableCamera(
        fov=45.0,
        elevation=20.0,
        azimuth=35.0,
        distance=4.5,
        center=(0.0, 0.0, 0.0),
    )
    _add_reference_geometry(view)


def main() -> None:
    canvas = scene.SceneCanvas(
        keys="interactive",
        show=True,
        size=(1350, 820),
        bgcolor=(0.02, 0.02, 0.025, 1.0),
        title="Raw VisPy sphere rendering matrix",
    )
    grid = canvas.central_widget.add_grid(spacing=8, margin=8)

    views = []
    for index, title in enumerate(CASES):
        case_row, column = divmod(index, 3)
        label_row = case_row * 2
        view_row = label_row + 1
        label = scene.Label(title, color="white", font_size=11)
        label.height_min = 34
        grid.add_widget(label, row=label_row, col=column)
        view = grid.add_view(row=view_row, col=column)
        _configure_view(view)
        views.append(view)

    # 1. Simplest possible scene.Sphere path.  No separate edge visual and no
    # state override: use SphereVisual's own depth-tested mesh defaults.
    sphere = scene.visuals.Sphere(
        radius=1.0,
        color=(1.0, 0.16, 0.04, 1.0),
        method="latitude",
        shading=None,
        parent=views[0].scene,
    )

    # 2. Different topology, still unlit and otherwise default.
    sphere = scene.visuals.Sphere(
        radius=1.0,
        color=(0.1, 1.0, 0.25, 1.0),
        method="ico",
        subdivisions=3,
        shading=None,
        parent=views[1].scene,
    )

    # 3. A third topology isolates latitude-pole or icosphere artifacts.
    sphere = scene.visuals.Sphere(
        radius=1.0,
        color=(0.1, 0.4, 1.0, 1.0),
        method="cube",
        subdivisions=3,
        shading=None,
        parent=views[2].scene,
    )

    # 4. Compare lighting against the clean unlit latitude baseline.
    sphere = scene.visuals.Sphere(
        radius=1.0,
        color=(1.0, 0.1, 0.75, 1.0),
        method="latitude",
        shading="smooth",
        parent=views[3].scene,
    )

    # 5. Bypass scene.Sphere and feed generated geometry to an unlit Mesh.
    mesh_data = create_sphere(rows=18, cols=24, radius=1.0, method="latitude")
    mesh = scene.visuals.Mesh(
        meshdata=mesh_data,
        color=(1.0, 0.58, 0.05, 1.0),
        shading=None,
        parent=views[4].scene,
    )
    mesh.set_gl_state("opaque", depth_test=True, cull_face="back")

    # 6. Explicit blending with rear faces culled to prevent double compositing.
    sphere = scene.visuals.Sphere(
        radius=1.0,
        color=(0.05, 0.9, 1.0, 0.4),
        method="ico",
        subdivisions=3,
        shading=None,
        parent=views[5].scene,
    )
    sphere.mesh.set_gl_state(
        blend=True,
        blend_func=("src_alpha", "one_minus_src_alpha"),
        depth_test=True,
        depth_mask=False,
        cull_face="back",
    )

    print("Raw VisPy sphere matrix opened; close the window to exit.", flush=True)
    app.run()


if __name__ == "__main__":
    main()
