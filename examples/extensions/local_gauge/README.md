# App-local widget scripts

This example is deliberately not a separately installable distribution. The
authoring declaration and Vispy renderer are two ordinary files beside the app.
Installing CompNeuroVis once is sufficient.

The authoring module records the deferred frontend callback with
`register_vispy_plugin("local_gauge_vispy:register")`. The callback module is
not imported in the backend process; the Vispy frontend imports it when it
constructs the UI.

Run from this directory:

```powershell
python demo.py
```
