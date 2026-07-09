"""Capture / compare a structural fingerprint of each example's built app-spec.

Usage:
  python golden.py capture   # writes golden.json
  python golden.py compare   # diffs current build vs golden.json
Pure restructuring must produce identical fingerprints.
"""
import json, os, runpy, sys
import compneurovis as cnv
import compneurovis.inline as inl
from compneurovis.inline import _reset_inline_session

OUT = os.path.join(os.path.dirname(__file__), "golden.json")

# Examples that build without external files / compiled mechanisms, across all 3 backends.
CASES = [
    "examples/custom/fitzhugh_nagumo_backend.py",
    "examples/custom/lif_backend.py",
    "examples/debug/two_line_plots.py",
    "examples/debug/multi_3d_views.py",
    "examples/surface_plot/animated_surface_live.py",
    "examples/surface_plot/static_surface_visualizer.py",
    "examples/surface_plot/surface_cross_section_visualizer.py",
    "examples/debug/two_morphology_views.py",
    "examples/neuron/hh_point_model_controls.py",
    "examples/neuron/hh_section_inspector.py",
    "examples/neuron/multicell_example.py",
    "examples/neuron/signaling_cascade_vis.py",
    "examples/jaxley/multicell_example.py",
]

ROOT = r"c:\Users\orren\Documents\PythonProjects\CompNeuroVis"

def fingerprint(app):
    lay = app.layout_catalog.active_layout()
    def field_fp(f):
        import numpy as np
        vals = getattr(f, "initial_values", None)
        shape = None if vals is None else tuple(np.asarray(vals).shape)
        return {"dims": list(f.dims), "shape": list(shape) if shape else None,
                "unit": f.unit, "coords": sorted(f.coords.keys()) if f.coords else []}
    return {
        "fields": {k: field_fp(v) for k, v in sorted(app.data.fields.items())},
        "geometries": sorted(app.data.geometries.keys()),
        "views": {k: type(v).__name__ for k, v in sorted(app.view_catalog.views.items())},
        "operators": sorted(app.view_catalog.operators.keys()),
        "controls": sorted(app.interactions.controls.keys()),
        "actions": sorted(app.interactions.actions.keys()),
        "panels": [{"id": p.id, "kind": p.kind, "views": list(p.view_ids),
                    "controls": list(p.control_ids), "actions": list(p.action_ids)} for p in lay.panels],
        "panel_grid": [list(r) for r in lay.panel_grid],
    }

def build(path):
    _reset_inline_session()
    cap = {}
    def fake_show(*a, **k):
        cap["grid"] = inl._app._panel_grid; cap["src"] = inl._app._sources[-1]
    orig = cnv.show; cnv.show = fake_show
    try:
        runpy.run_path(os.path.join(ROOT, path), run_name="__notmain__")
        src = cap["src"]
        if cap.get("grid") is not None: src._panel_grid = cap["grid"]
        be = src._make_backend()
        return fingerprint(src._build_app_spec_for_backend(be))
    finally:
        cnv.show = orig

def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "compare"
    results = {}
    for p in CASES:
        try:
            results[p] = build(p)
        except Exception as e:
            results[p] = {"ERROR": f"{type(e).__name__}: {e}"}
    if mode == "capture":
        with open(OUT, "w") as f:
            json.dump(results, f, indent=2, sort_keys=True)
        print(f"captured {len(results)} fingerprints -> {OUT}")
    else:
        with open(OUT) as f:
            golden = json.load(f)
        ok = True
        for p in CASES:
            g = json.dumps(golden.get(p), sort_keys=True)
            c = json.dumps(results.get(p), sort_keys=True)
            if g == c:
                print(f"OK    {os.path.basename(p)}")
            else:
                ok = False
                print(f"DIFF  {os.path.basename(p)}")
                print("  golden :", g[:400])
                print("  current:", c[:400])
        print("ALL IDENTICAL" if ok else "!!! DIFFERENCES FOUND")

if __name__ == "__main__":
    main()
