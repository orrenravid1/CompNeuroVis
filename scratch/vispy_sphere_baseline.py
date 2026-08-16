"""Minimal raw-VisPy sphere baseline: one canvas, one view, one mesh."""

from __future__ import annotations

from vispy import app, scene


def main() -> None:
    canvas = scene.SceneCanvas(
        keys="interactive",
        show=True,
        size=(900, 700),
        bgcolor=(0.04, 0.045, 0.055, 1.0),
        title="Raw VisPy single-sphere baseline",
    )
    view = canvas.central_widget.add_view()

    sphere = scene.visuals.Sphere(
        radius=1.0,
        method="cube",
        subdivisions=4,
        color=(0.12, 0.48, 1.0, 1.0),
        shading=None,
        parent=view.scene,
    )
    sphere.mesh.set_gl_state(
        "opaque",
        depth_test=True,
        cull_face="back",
    )

    view.camera = scene.cameras.TurntableCamera(
        fov=45.0,
        elevation=20.0,
        azimuth=35.0,
        distance=4.5,
        center=(0.0, 0.0, 0.0),
    )
    view.camera.set_range(
        x=(-1.25, 1.25),
        y=(-1.25, 1.25),
        z=(-1.25, 1.25),
        margin=0.05,
    )

    print(
        "Single raw VisPy sphere opened. Drag to rotate; wheel to zoom.",
        flush=True,
    )
    app.run()


if __name__ == "__main__":
    main()
