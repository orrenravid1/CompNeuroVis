# App-local point-cloud widget

This example implements the complete PointCloud3D, plane-slice, and Scatter2D
composition as ordinary files beside an app. It is not a Python package and has
no separate installation step. Installing CompNeuroVis once is sufficient.

Run it directly from this directory:

```powershell
python demo.py
```

The CompNeuroVis backend process receives only neutral geometry, field, and view
specs. Importing `pointcloud.py` records the deferred
`pointcloud_vispy:register` callback. The frontend imports that adjacent module
only when it constructs the UI; the callback registers the 3-D visual, 2-D
scatter host, plane-slice operator adapter, and slice-owned overlay.

The files demonstrate the intended separation:

- `pointcloud.py` owns frontend-neutral widget authoring.
- `pointcloud_slice.py` owns the neutral slice computation.
- `pointcloud_vispy.py` owns Vispy and Qt presentation plus registration.
- `demo.py` composes the widgets and controls into an app.

The demo deliberately shows two clouds whose entity ids overlap. Clicking a
point highlights it only in the panel that owns that selection.

The controls drive a finite plane slice through Cloud A. The translucent slab
boundaries update in its 3-D panel, while the separate Scatter2D widget renders
the selected points projected into the plane. Cloud B remains unrelated.
