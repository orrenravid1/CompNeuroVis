"""Run the app-local PointCloud3D widget without installing another package."""

from __future__ import annotations

import numpy as np

import compneurovis as cnv
from pointcloud import PointCloud3D, PointCloudPlaneSlice, Scatter2D


rng = np.random.default_rng(7)
positions = rng.normal(size=(240, 3)).astype(np.float32)
values = np.linalg.norm(positions, axis=1).astype(np.float32)

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
    min=0.01,
    max=0.75,
    default=0.2,
)
cloud_a = source.add(
    PointCloud3D(
        "External point cloud A",
        positions=positions,
        values=values,
        style={
            "point_size": 9.0,
            "background_color": "#f7f7f7",
            "camera_distance": 8.0,
            "camera_elevation": 24.0,
            "camera_azimuth": 38.0,
        },
    )
)
cloud_b = source.add(
    PointCloud3D(
        "External point cloud B",
        positions=(positions * np.array((0.65, 1.2, 0.8), dtype=np.float32)),
        values=values[::-1],
        style={
            "point_size": 9.0,
            "background_color": "#f7f7f7",
            "camera_distance": 8.0,
            "camera_elevation": 24.0,
            "camera_azimuth": 38.0,
        },
    )
)
slice_data = source.add(
    PointCloudPlaneSlice(
        "Cloud A plane slice",
        source=cloud_a,
        axis=axis,
        position=position,
        thickness=thickness,
        overlay={"color": "#ff9d00", "alpha": 0.16},
    )
)
scatter = source.add(
    Scatter2D(
        "Projected slice",
        source=slice_data,
        style={"point_size": 10.0},
    )
)
cnv.layout(
    (
        (cloud_a, cloud_b),
        (scatter, source.controls_panel),
    )
)
cnv.show(title="App-local PointCloud3D")
