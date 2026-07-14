"""Capture/compare a per-tick emission fingerprint of a source backend.

Drives one example's backend through initialize -> ticks -> reset -> ticks and
records every emitted message (type, field id, shape, value checksum). The tick
refactor must reproduce this sequence identically.

Usage:
  python runtime_golden.py capture <example.py> <out.json>
  python runtime_golden.py compare <example.py> <out.json>
Run one example per process (NEURON/jax use global sim state).
"""
import json, os, runpy, sys
import numpy as np
import compneurovis as cnv
import compneurovis.inline as inl
from compneurovis.inline import _reset_inline_session
from compneurovis.core.messages import command_message, Reset, SetControl

ROOT = r"c:\Users\orren\Documents\PythonProjects\CompNeuroVis"


def _msg_fp(payload):
    t = type(payload).__name__
    fid = getattr(payload, "field_id", None)
    vals = getattr(payload, "values", None)
    shape = None
    checksum = None
    if vals is not None:
        arr = np.asarray(vals, dtype=np.float64)
        shape = list(arr.shape)
        s = float(np.nansum(arr))
        checksum = round(s, 3)
    # BindingValuePatch / Status etc: capture keys/text
    extra = None
    if hasattr(payload, "values_by_key"):
        extra = sorted(payload.values_by_key.keys())
    elif hasattr(payload, "patch"):
        try:
            extra = sorted(payload.patch.keys())
        except Exception:
            extra = None
    return {"t": t, "field": fid, "shape": shape, "sum": checksum, "extra": extra}


def _drain(backend):
    return [_msg_fp(m.payload) for m in backend.take_outbound_messages()]


def build_backend(path):
    _reset_inline_session()
    cap = {}
    def fake_show(*a, **k):
        cap["grid"] = inl._app._panel_grid
        cap["src"] = inl._app._sources[-1]
    cnv.show = fake_show
    runpy.run_path(os.path.join(ROOT, path), run_name="__notmain__")
    src = cap["src"]
    if cap.get("grid") is not None:
        src._panel_grid = cap["grid"]
    backend = src._make_backend()
    app_spec = src._build_app_spec_for_backend(backend)
    backend.initialize(app_spec)
    return backend, src


def _apply_first_control(backend, src):
    """Drive the control path: set the first source control to its max, capturing
    the effect. Returns the drained messages, or None if there are no controls."""
    controls = getattr(src, "_controls", [])
    if not controls:
        return None
    control = controls[0]
    value = float(getattr(control, "max", 1.0))
    if os.environ.get("USE_VALUE_CHANGE"):
        from compneurovis.core.messages import ValueChange
        backend.handle(command_message(ValueChange({control._control_id: value})))
    else:
        backend.handle(command_message(SetControl(control._control_id, value)))
    return _drain(backend)


def run(path):
    backend, src = build_backend(path)
    seq = {"init": _drain(backend), "ticks": [], "control": None, "post_control": [],
           "reset": None, "post_reset": []}
    for _ in range(15):
        backend.tick()
        seq["ticks"].append(_drain(backend))
    seq["control"] = _apply_first_control(backend, src)
    for _ in range(10):
        backend.tick()
        seq["post_control"].append(_drain(backend))
    backend.handle(command_message(Reset()))
    seq["reset"] = _drain(backend)
    for _ in range(5):
        backend.tick()
        seq["post_reset"].append(_drain(backend))
    return seq


def main():
    mode, path, out = sys.argv[1], sys.argv[2], sys.argv[3]
    seq = run(path)
    if mode == "capture":
        with open(out, "w") as f:
            json.dump(seq, f, indent=1)
        n = len(seq["init"]) + sum(len(t) for t in seq["ticks"])
        print(f"CAPTURED {path}: {len(seq['ticks'])} ticks, {n} msgs -> {out}")
    else:
        with open(out) as f:
            golden = json.load(f)
        a = json.dumps(golden, sort_keys=True)
        b = json.dumps(seq, sort_keys=True)
        if a == b:
            print(f"OK    {path}  (runtime emissions identical)")
        else:
            print(f"DIFF  {path}")
            # find first differing tick
            for i, (g, c) in enumerate(zip(golden["ticks"], seq["ticks"])):
                if g != c:
                    print(f"  first tick diff at #{i}:")
                    print(f"    golden : {g}")
                    print(f"    current: {c}")
                    break
            else:
                if golden["init"] != seq["init"]:
                    print(f"  init diff:\n   golden : {golden['init']}\n   current: {seq['init']}")
                if golden["reset"] != seq["reset"]:
                    print(f"  reset diff:\n   golden : {golden['reset']}\n   current: {seq['reset']}")


if __name__ == "__main__":
    main()
