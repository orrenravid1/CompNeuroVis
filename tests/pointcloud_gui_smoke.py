"""Render the separately installed point-cloud fixture through the real Vispy host.

This is an explicit GUI conformance check rather than part of the headless golden
suite. It installs the fixture into a temporary site directory, authors through
the public package API, then uses the framework frontend boundary to verify that
entry-point discovery mounts and draws the package-owned visual.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import shutil
import site
import subprocess
import sys
import tempfile

import numpy as np
from PyQt6 import QtWidgets

import compneurovis as cnv
import compneurovis.inline as inline
from compneurovis.frontends.vispy.frontend import VispyFrontendWindow
from compneurovis.frontends.vispy.host import _configure_qt_surface_format


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "extensions" / "cnv_pointcloud_demo"


def _installed_package(temp_dir: Path):
    fixture_copy = temp_dir / "fixture"
    shutil.copytree(FIXTURE, fixture_copy)
    target = temp_dir / "site"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-deps",
            "--no-build-isolation",
            "--target",
            str(target),
            str(fixture_copy),
        ],
        check=True,
    )
    site.addsitedir(str(target))
    importlib.invalidate_caches()
    return importlib.import_module("cnv_pointcloud_demo")


def _app_spec(pointcloud):
    inline._reset_inline_session()
    source = cnv.source()
    axis = source.dropdown(
        "slice_axis",
        label="Slice axis",
        options=("x", "y", "z"),
        default="z",
    )
    position = source.slider(
        "slice_position",
        label="Slice position",
        min=0.0,
        max=1.0,
        default=0.5,
    )
    thickness = source.slider(
        "slice_thickness",
        label="Slice thickness",
        min=0.0,
        max=1.0,
        default=0.75,
    )
    cloud = source.add(
        pointcloud.PointCloud3D(
            "Rendered external cloud",
            positions=np.array(
                [
                    [-1.0, -0.5, -0.25],
                    [0.0, 0.75, 0.5],
                    [1.0, -0.25, 0.75],
                ],
                dtype=np.float32,
            ),
            values=np.array([0.0, 0.5, 1.0], dtype=np.float32),
            style={
                "point_size": 28.0,
                "camera_distance": 5.0,
                "background_color": "white",
            },
        )
    )
    slice_data = source.add(
        pointcloud.PointCloudPlaneSlice(
            "Rendered slice",
            source=cloud,
            axis=axis,
            position=position,
            thickness=thickness,
        )
    )
    scatter = source.add(
        pointcloud.Scatter2D(
            "Rendered scatter",
            source=slice_data,
        )
    )
    cnv.layout(((cloud, scatter), (source.controls_panel,)))
    source._panel_grid = inline._app._panel_grid
    backend = source._make_backend()
    return source._build_app_spec_for_backend(backend)


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="cnv-pointcloud-gui-") as raw_temp:
        pointcloud = _installed_package(Path(raw_temp))
        app_spec = _app_spec(pointcloud)

        _configure_qt_surface_format()
        qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        window = VispyFrontendWindow(title="PointCloud3D GUI conformance")
        window.initialize(app_spec)
        window.resize(640, 480)
        window.show()
        for _ in range(8):
            qapp.processEvents()

        assert len(window.view_hosts) == 1
        assert len(window.extension_hosts) == 1
        host = next(iter(window.view_hosts.values()))
        assert host.viewport.active_visual_key == "point_cloud_3d"
        visual = host.visual("point_cloud_3d")
        assert visual._markers.visible
        assert len(visual._slice_planes) == 2

        scatter_host = next(iter(window.extension_hosts.values()))
        scatter_x, scatter_y = scatter_host._scatter.getData()
        assert len(scatter_x) == len(scatter_y) > 0

        frame = np.asarray(host.viewport.canvas.render(alpha=True))
        assert frame.ndim == 3 and frame.shape[2] == 4
        assert np.unique(frame.reshape(-1, 4), axis=0).shape[0] > 1

        print(
            json.dumps(
                {
                    "visual": host.viewport.active_visual_key,
                    "frame_shape": list(frame.shape),
                    "distinct_rgba": int(
                        np.unique(frame.reshape(-1, 4), axis=0).shape[0]
                    ),
                    "slice_planes": len(visual._slice_planes),
                    "scatter_points": len(scatter_x),
                },
                sort_keys=True,
            )
        )
        window.close()
        qapp.processEvents()


if __name__ == "__main__":
    main()
