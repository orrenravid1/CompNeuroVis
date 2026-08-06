"""Run the separately packaged PointCloud3D conformance widget."""

from __future__ import annotations

import numpy as np

import compneurovis as cnv
from cnv_pointcloud_demo import PointCloud3D


rng = np.random.default_rng(7)
positions = rng.normal(size=(240, 3)).astype(np.float32)
values = np.linalg.norm(positions, axis=1).astype(np.float32)

source = cnv.source()
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
cnv.layout(((cloud_a, cloud_b),))
cnv.show(title="External PointCloud3D")
