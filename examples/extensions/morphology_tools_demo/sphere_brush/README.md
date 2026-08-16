# Spherical morphology brush

Run the small dependency-free diagnostic example from the repository root:

~~~powershell
python examples/extensions/morphology_tools_demo/sphere_brush/run.py
~~~

Run the full SWC example (requires NEURON):

~~~powershell
python examples/extensions/morphology_tools_demo/sphere_brush/run_swc.py
~~~

Enable **Sphere brush mode**. The translucent sphere follows the pointer ray at
the depth of the nearest morphology segment. Adjust its radius and paint value
with the sliders, then click to color every morphology cylinder intersecting the
sphere. The press is claimed only when that volume overlaps the morphology; it
does not depend on the pointer's center pixel hitting an entity.

The preview observes portable pointer events locally in the frontend; it neither
claims the pointer nor sends hover traffic to the backend. A press is an explicit
captured interaction and performs one backend-authoritative field update.
