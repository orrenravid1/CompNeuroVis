# CompNeuroVis point-cloud conformance fixture

This is intentionally an installable Python distribution because it is the
installed-plugin conformance fixture. Separate packaging is not required for
normal widget authoring; `../local_gauge` proves the adjacent-script path.

It is an architecture fixture, not a built-in widget or a compatibility package.

Install it as its own distribution and run the example from this directory:

```powershell
python -m pip install .
python demo.py
```

The CompNeuroVis backend process receives only neutral geometry, field, and view
specs. The frontend discovers one callback from the
`compneurovis.vispy_plugins` entry-point group; that callback registers its 3-D
visual, 2-D scatter host, and operator adapter.

The demo deliberately shows two clouds whose entity ids overlap. Clicking a
point highlights it only in the panel that owns that selection.

The controls drive a finite plane slice through Cloud A. The translucent slab
boundaries update in its 3-D panel, while the separate Scatter2D widget renders
the selected points projected into the plane. Cloud B remains unrelated.
