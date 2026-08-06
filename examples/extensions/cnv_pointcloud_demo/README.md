# CompNeuroVis point-cloud conformance fixture

This is intentionally a separate Python distribution. It proves that a widget
package can own its typed declaration and Vispy renderer while lowering only
neutral CompNeuroVis specs into the application.

It is an architecture fixture, not a built-in widget or a compatibility package.

Install it as its own distribution and run the example from this directory:

```powershell
python -m pip install .
python demo.py
```

The CompNeuroVis backend process receives only neutral geometry, field, and view
specs. The frontend discovers the package-owned Vispy renderer from the
`compneurovis.vispy_plugins` entry-point group.

The demo deliberately shows two clouds whose entity ids overlap. Clicking a
point highlights it only in the panel that owns that selection.
