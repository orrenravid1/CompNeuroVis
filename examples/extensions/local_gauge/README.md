# App-local widget scripts

This example is deliberately not a separately installable distribution. The
authoring declaration and Vispy renderer are two ordinary files beside the app.
Installing CompNeuroVis once is sufficient.

The authoring module records the deferred frontend callback with
`register_vispy_plugin("local_gauge_vispy:register")`. The callback module is
not imported in the backend process; the Vispy frontend imports it when it
constructs the UI. This example intentionally registers a complete custom panel
kind (`local_gauge_panel`) -- construction, refresh-target ownership, visibility,
sizing intent, and disposal -- to exercise the open panel-host boundary. Most
standalone widgets should use the ordinary `standalone` panel instead.

Run from this directory:

```powershell
python demo.py
```
