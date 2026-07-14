---
name: debug-protocol-dataflow
description: Trace live data and commands across source, backend actor, bus, and frontend boundaries.
---

# Debug Protocol Dataflow

Treat current src/ as authority. Do not begin from architecture docs or old
tests.

Debug in this order:

1. Reduce failure to smallest source declaration that still reproduces it.
2. Confirm source binding or simulator-native collector reads expected value.
3. Confirm backend actor emits expected typed update with fragment tag.
4. Confirm bus route delivers update to intended actor.
5. Confirm frontend projection stores update under expected scoped reference.
6. Confirm refresh planner targets expected view and panel.
7. Trace command path in reverse for controls, actions, and selection.

Use existing logging framework. Add temporary boundary timing or count logs when
needed, then remove noisy diagnostics after cause is known. Preserve NEURON and
Jaxley native collectors when fixing shared source behavior.
