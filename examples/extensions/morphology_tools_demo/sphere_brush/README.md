# Spherical morphology brush

Run the small dependency-free diagnostic example from the repository root:

~~~powershell
python examples/extensions/morphology_tools_demo/sphere_brush/run.py
~~~

Run the full SWC example (requires NEURON):

~~~powershell
python examples/extensions/morphology_tools_demo/sphere_brush/run_swc.py
~~~

Run a live HH simulation whose spatial model parameters can be painted:

~~~powershell
python examples/extensions/morphology_tools_demo/sphere_brush/run_neuron_live.py
~~~

The live example has explicit **Live view** and **Paint** modes. Live view shows
one chosen simulation variable. Paint mode hides that selector, shows one paint
target and only its relevant value slider, and atomically retargets the
morphology's current data, palette, limits, and unit. It can edit `gnabar_hh`,
`gkbar_hh`, segment `cm`, or section `Ra`. Each completed stroke logs concise
values read back from the affected NEURON model owners.

In Paint mode, the translucent sphere follows the pointer ray at the depth of
the nearest morphology segment. Adjust its radius and paint value, then click or
drag to edit every morphology cylinder intersecting the sphere. The press is
claimed only when that volume overlaps the morphology; it does not depend on the
pointer's center pixel hitting an entity.

The preview observes portable pointer events locally in the frontend; it neither
claims the pointer nor sends hover traffic to the backend. A press is an explicit
captured interaction and performs one backend-authoritative field update.
